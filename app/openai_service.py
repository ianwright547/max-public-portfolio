"""Optional OpenAI interpretation adapter.

The adapter is isolated from Max's core workflow. It never runs unless the
caller explicitly requests `mode=openai`, and it returns only validated JSON.
"""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app import models


class OpenAIInterpretationError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def model_for_role(role: str) -> str:
    names = {
        "quality": os.getenv("OPENAI_MODEL_SOL", "gpt-5.6-sol"),
        "balanced": os.getenv("OPENAI_MODEL_BALANCED", "gpt-5.6-terra"),
        "efficient": os.getenv("OPENAI_MODEL_EFFICIENT", "gpt-5.6-luna"),
    }
    if role not in names:
        raise OpenAIInterpretationError("openai_invalid_model_role")
    return names[role]


def _extract_json(response: dict) -> dict:
    text = response.get("output_text")
    if not text:
        for item in response.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    text = content.get("text")
                    break
            if text:
                break
    if not isinstance(text, str):
        raise OpenAIInterpretationError("openai_missing_structured_output")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise OpenAIInterpretationError("openai_invalid_json") from error
    if not isinstance(value, dict):
        raise OpenAIInterpretationError("openai_invalid_profile_shape")
    required = {"profile_data", "missing_information", "conflicting_information"}
    if not required.issubset(value):
        raise OpenAIInterpretationError("openai_profile_schema_mismatch")
    return value


def interpret(
    intake: models.Intake,
    business_name: str,
    *,
    role: str = "balanced",
    system_prompt: str | None = None,
    user_prompt: str | None = None,
) -> tuple[dict, list[str], list[str], str]:
    """Interpret one intake through the Responses API and validate its shape."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise OpenAIInterpretationError("openai_api_key_missing")
    payload = {
        "model": model_for_role(role),
        "input": [
            {
                "role": "system",
                "content": system_prompt or "Return JSON only. Never invent information. Preserve the source fields exactly.",
            },
            {
                "role": "user",
                "content": user_prompt or json.dumps({
                    "business_name": business_name,
                    "phone_number": intake.phone_number,
                    "email": intake.email,
                    "brand_colors": intake.brand_colors,
                    "domain": intake.domain,
                    "business_hours": intake.business_hours,
                    "service_areas": intake.service_areas,
                    "google_business_profile": intake.google_business_profile,
                    "enabled_workflows": intake.enabled_workflows,
                }),
            },
        ],
        "text": {"format": {"type": "json_object"}},
    }
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 429 or error.code >= 500:
            raise OpenAIInterpretationError("openai_temporarily_unavailable", retryable=True) from error
        if error.code in {401, 403}:
            raise OpenAIInterpretationError("openai_authorization_failed") from error
        raise OpenAIInterpretationError("openai_request_failed") from error
    except (URLError, TimeoutError) as error:
        raise OpenAIInterpretationError("openai_temporarily_unavailable", retryable=True) from error
    value = _extract_json(body)
    profile = value["profile_data"]
    missing = value["missing_information"]
    conflicts = value["conflicting_information"]
    if not isinstance(profile, dict) or not isinstance(missing, list) or not isinstance(conflicts, list):
        raise OpenAIInterpretationError("openai_profile_schema_mismatch")
    return profile, [str(item) for item in missing], [str(item) for item in conflicts], "ready_for_review"
