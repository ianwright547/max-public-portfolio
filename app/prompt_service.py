"""Versioned, auditable prompt compilation for client AI work."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.audit import record_event


PROMPT_VERSION = "1.0"
KNOWLEDGE_ROOT = Path(__file__).resolve().parent.parent / "docs" / "knowledge"

PURPOSE_KNOWLEDGE = {
    "onboarding_interpretation": ["sops/02-client-onboarding.md"],
    "fulfillment_plan": ["sops/09-fulfillment-plan.md", "sops/10-task-execution.md"],
    "website_generation": ["sops/07-website-generation.md", "sops/08-website-changes-and-publishing.md"],
    "website_audit": ["skills/local-website-audit/SKILL.md", "sops/local-seo/07-local-website-audit.md"],
    "gbp_draft": ["sops/18-google-business-profile.md"],
    "reporting": ["sops/13-reporting.md", "sops/12-metrics-and-data-sources.md"],
}


class PromptCompilationError(ValueError):
    """Raised when a prompt cannot be compiled from approved records."""


def _knowledge_files(purpose: str) -> list[str]:
    files = PURPOSE_KNOWLEDGE.get(purpose)
    if files is None:
        raise PromptCompilationError(f"unsupported_prompt_purpose:{purpose}")
    missing = [path for path in files if not (KNOWLEDGE_ROOT / path).is_file()]
    if missing:
        raise PromptCompilationError(f"knowledge_file_missing:{missing[0]}")
    return files


def _load_knowledge(files: list[str]) -> str:
    return "\n\n".join(
        f"===== {path} =====\n{(KNOWLEDGE_ROOT / path).read_text(encoding='utf-8')}"
        for path in files
    )


def compile_prompt(
    database: Session,
    *,
    operation_key: str,
    client_id: str,
    purpose: str,
    model_role: str = "balanced",
    intake_id: str | None = None,
    task_id: str | None = None,
) -> tuple[models.PromptArtifact, bool]:
    """Compile and persist a deterministic prompt artifact, idempotently."""
    existing = database.scalar(
        select(models.PromptArtifact).where(models.PromptArtifact.operation_key == operation_key)
    )
    if existing is not None:
        if existing.client_id != client_id or existing.purpose != purpose:
            raise PromptCompilationError("operation_key_belongs_to_different_prompt")
        return existing, True

    client = database.get(models.Client, client_id)
    if client is None:
        raise PromptCompilationError("client_not_found")
    profile = database.scalar(
        select(models.OfficialProfile).where(models.OfficialProfile.client_id == client_id)
    )
    intake = database.get(models.Intake, intake_id) if intake_id else None
    if intake_id and (intake is None or intake.client_id != client_id):
        raise PromptCompilationError("intake_not_found_for_client")
    if profile is None and not (purpose == "onboarding_interpretation" and intake is not None):
        raise PromptCompilationError("official_profile_required")
    task = database.get(models.Task, task_id) if task_id else None
    if task_id and (task is None or task.client_id != client_id):
        raise PromptCompilationError("task_not_found_for_client")

    files = _knowledge_files(purpose)
    input_snapshot = {
        "client": {"id": client.id, "business_name": client.business_name},
        "official_profile_id": profile.id if profile else None,
        "approved_client_facts": profile.profile_data if profile else None,
        "intake_id": intake.id if intake else None,
        "source_intake": ({
            "phone_number": intake.phone_number,
            "email": intake.email,
            "brand_colors": intake.brand_colors,
            "domain": intake.domain,
            "business_hours": intake.business_hours,
            "service_areas": intake.service_areas,
            "google_business_profile": intake.google_business_profile,
            "enabled_workflows": intake.enabled_workflows,
        } if intake else None),
        "task": ({"id": task.id, "title": task.title, "requested_outcome": task.requested_outcome} if task else None),
    }
    system_prompt = (
        "You are Max. Use only the approved client facts and task scope supplied below. "
        "Never invent business facts, services, locations, testimonials, rankings, revenue, or results. "
        "Separate observations, recommendations, uncertainty, and completed work."
    )
    user_prompt = (
        f"Purpose: {purpose}\nModel role: {model_role}\n"
        f"Approved context:\n{json.dumps(input_snapshot, sort_keys=True, indent=2)}\n\n"
        f"Reusable knowledge:\n{_load_knowledge(files)}"
    )
    content_hash = sha256((system_prompt + "\n" + user_prompt).encode("utf-8")).hexdigest()
    artifact = models.PromptArtifact(
        operation_key=operation_key,
        client_id=client_id,
        intake_id=intake_id,
        task_id=task_id,
        purpose=purpose,
        prompt_version=PROMPT_VERSION,
        model_role=model_role,
        input_snapshot=input_snapshot,
        knowledge_files=files,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        content_hash=content_hash,
    )
    database.add(artifact)
    database.commit()
    database.refresh(artifact)
    record_event(
        database,
        "prompt_artifact_compiled",
        client_id=client_id,
        record_type="prompt_artifact",
        record_id=artifact.id,
        details={"purpose": purpose, "prompt_version": PROMPT_VERSION, "content_hash": content_hash},
    )
    database.commit()
    return artifact, False
