"""Replaceable onboarding interpretation service.

This phase deliberately uses deterministic local logic. A future OpenAI adapter
can implement the same `interpret` contract without changing the route or model.
"""

from typing import Optional

from app import models


def interpret(
    intake: models.Intake,
    business_name: str,
    asset_references: Optional[list[str]] = None,
) -> tuple[dict, list[str], list[str], str]:
    """Turn one saved intake into a proposed profile without inventing values."""
    profile = {
        "business_information": {"business_name": business_name},
        "contact_information": {"phone_number": intake.phone_number, "email": intake.email},
        "brand_information": {"brand_colors": intake.brand_colors},
        "domain": intake.domain,
        "business_hours": intake.business_hours,
        "service_areas": intake.service_areas,
        "google_business_profile": intake.google_business_profile,
        "enabled_workflows": intake.enabled_workflows,
        "asset_references": asset_references or [],
    }
    missing: list[str] = []
    conflicts: list[str] = []

    for field, value in {
        "phone_number": intake.phone_number,
        "email": intake.email,
        "domain": intake.domain,
        "business_hours": intake.business_hours,
        "google_business_profile": intake.google_business_profile,
    }.items():
        if not str(value or "").strip():
            missing.append(field)
    for field, value in {
        "brand_colors": intake.brand_colors,
        "service_areas": intake.service_areas,
        "enabled_workflows": intake.enabled_workflows,
    }.items():
        if not value:
            missing.append(field)

    # The raw intake has one value per field in Phase 1, so the fake interpreter
    # can only report structural conflicts, never guess between values.
    if isinstance(intake.brand_colors, list) and len(set(intake.brand_colors)) != len(intake.brand_colors):
        conflicts.append("brand_colors contains duplicate values")

    status = "needs_review" if missing or conflicts else "ready_for_review"
    return profile, missing, conflicts, status
