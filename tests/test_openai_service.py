"""Tests for the optional OpenAI adapter without making network requests."""

import json

import pytest

from app.openai_service import OpenAIInterpretationError, _extract_json, model_for_role


def test_model_roles_use_configured_defaults() -> None:
    assert model_for_role("quality") == "gpt-5.6-sol"
    assert model_for_role("balanced") == "gpt-5.6-terra"
    assert model_for_role("efficient") == "gpt-5.6-luna"


def test_invalid_model_role_is_rejected() -> None:
    with pytest.raises(OpenAIInterpretationError, match="openai_invalid_model_role"):
        model_for_role("unknown")


def test_structured_output_is_validated() -> None:
    result = _extract_json({"output_text": json.dumps({"profile_data": {}, "missing_information": [], "conflicting_information": []})})
    assert result["profile_data"] == {}


def test_invalid_structured_output_is_rejected() -> None:
    with pytest.raises(OpenAIInterpretationError, match="openai_profile_schema_mismatch"):
        _extract_json({"output_text": "{}"})
