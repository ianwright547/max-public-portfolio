"""OpenAI-backed website file generation with strict structured validation."""

from __future__ import annotations

import json
import os
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app import models
from app.ai_cost_service import AIBudgetExceeded, ensure_budget, record_usage
from app.openai_service import model_for_role
from app.prompt_service import compile_prompt
from app.website_execution import validate_files, WebsiteExecutionError
from sqlalchemy import select


class WebsiteGenerationError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


WEBSITE_GENERATION_ESTIMATE_USD = 0.05


def _output_json(payload: dict) -> dict:
    text = payload.get("output_text")
    if not isinstance(text, str):
        for item in payload.get("output", []) or []:
            for content in item.get("content", []) or []:
                if content.get("type") in {"output_text", "text"}:
                    text = content.get("text")
                    break
            if isinstance(text, str):
                break
    try:
        value = json.loads(text) if isinstance(text, str) else None
    except json.JSONDecodeError as error:
        raise WebsiteGenerationError("website_generation_invalid_json") from error
    if not isinstance(value, dict) or not isinstance(value.get("files"), list):
        raise WebsiteGenerationError("website_generation_file_schema_mismatch")
    files = []
    for item in value["files"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("content"), str):
            raise WebsiteGenerationError("website_generation_file_schema_mismatch")
        files.append({"path": item["path"], "content": item["content"]})
    return {"files": files}


def generate_files(database, task: models.Task, *, model_role: str = "quality") -> tuple[list[dict[str, str]], str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise WebsiteGenerationError("openai_api_key_missing")
    operation_key = f"website-generation:{task.id}"
    existing_usage = database.scalar(
        select(models.AIUsageRecord).where(models.AIUsageRecord.operation_key == operation_key)
    )
    if existing_usage is None:
        try:
            ensure_budget(database, WEBSITE_GENERATION_ESTIMATE_USD, datetime.utcnow())
        except AIBudgetExceeded as error:
            raise WebsiteGenerationError("monthly_ai_budget_exceeded") from error
    artifact, _ = compile_prompt(
        database,
        operation_key=f"prompt:website-generation:{task.id}",
        client_id=task.client_id,
        task_id=task.id,
        purpose="website_generation",
        model_role=model_role,
    )
    payload = {
        "model": model_for_role(model_role),
        "input": [
            {"role": "system", "content": artifact.system_prompt + " Return JSON with a files array only."},
            {"role": "user", "content": artifact.user_prompt},
        ],
        "text": {"format": {"type": "json_object"}},
    }
    try:
        with urlopen(
            Request(
                "https://api.openai.com/v1/responses",
                data=json.dumps(payload).encode(),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                method="POST",
            ),
            timeout=90,
        ) as response:
            raw_result = json.loads(response.read().decode())
            usage = raw_result.get("usage") if isinstance(raw_result, dict) else {}
            input_tokens = usage.get("input_tokens") if isinstance(usage, dict) and isinstance(usage.get("input_tokens"), int) else None
            output_tokens = usage.get("output_tokens") if isinstance(usage, dict) and isinstance(usage.get("output_tokens"), int) else None
            record_usage(
                database,
                operation_key=operation_key,
                client_id=task.client_id,
                task_id=task.id,
                provider="openai",
                model=model_for_role(model_role),
                model_role=model_role,
                operation="website_generation",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=WEBSITE_GENERATION_ESTIMATE_USD,
                actual_cost_usd=None,
            )
            # Provider spend is a durable commercial fact. Commit the ledger
            # before parsing/validating the model output so a later route
            # rollback (for malformed JSON or unsafe files) cannot erase the
            # recorded usage and allow a retry to bypass the monthly budget.
            database.commit()
            result = _output_json(raw_result)
    except HTTPError as error:
        raise WebsiteGenerationError("openai_website_generation_failed", retryable=error.code == 429 or error.code >= 500) from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise WebsiteGenerationError("openai_website_generation_unavailable", retryable=True) from error
    try:
        validate_files(result["files"], ["app/**", "public/**"], [".env*", "**/.env*", ".git/**", "node_modules/**"])
    except WebsiteExecutionError as error:
        raise WebsiteGenerationError(str(error)) from error
    return result["files"], artifact.id
