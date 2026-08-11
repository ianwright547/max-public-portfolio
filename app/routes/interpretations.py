"""Onboarding interpretation endpoints."""

from datetime import datetime, timezone

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import interpretation_service, models, schemas
from app.ai_cost_service import AIBudgetExceeded, ensure_budget, record_usage
from app.database import get_database
from app.openai_service import OpenAIInterpretationError
from app.prompt_service import compile_prompt

router = APIRouter(tags=["interpretations"])


@router.post(
    "/intakes/{intake_id}/interpret",
    response_model=schemas.InterpretationRead,
    status_code=status.HTTP_201_CREATED,
)
def interpret_intake(
    intake_id: str,
    mode: Literal["fake", "openai"] = Query("fake"),
    model_role: Literal["quality", "balanced", "efficient"] = Query("balanced"),
    database: Session = Depends(get_database),
) -> models.InterpretationProposal:
    intake = database.get(models.Intake, intake_id)
    if intake is None:
        raise HTTPException(status_code=404, detail="Intake not found")

    existing = database.scalar(
        select(models.InterpretationProposal).where(models.InterpretationProposal.intake_id == intake_id)
    )
    if existing is not None:
        return existing

    client = database.get(models.Client, intake.client_id)
    if client is None:
        raise HTTPException(status_code=409, detail="Intake is linked to a missing client")
    try:
        if mode == "openai":
            from app import openai_service
            import os

            try:
                estimated_cost = max(0.0, float(os.getenv("OPENAI_INTERPRETATION_ESTIMATED_COST_USD", "0.05")))
            except ValueError:
                estimated_cost = 0.05
            try:
                ensure_budget(database, estimated_cost, datetime.utcnow())
            except AIBudgetExceeded as error:
                raise HTTPException(status_code=429, detail=str(error)) from error

            prompt_artifact, _ = compile_prompt(
                database,
                operation_key=f"prompt:openai-interpret:{intake.id}",
                client_id=client.id,
                intake_id=intake.id,
                purpose="onboarding_interpretation",
                model_role=model_role,
            )
            profile, missing, conflicts, processing_status = openai_service.interpret(
                intake,
                client.business_name,
                role=model_role,
                system_prompt=prompt_artifact.system_prompt,
                user_prompt=prompt_artifact.user_prompt,
            )
            record_usage(
                database,
                operation_key=f"openai-interpret:{intake.id}",
                client_id=client.id,
                task_id=None,
                provider="openai",
                model=openai_service.model_for_role(model_role),
                model_role=model_role,
                operation="onboarding_interpretation",
                input_tokens=None,
                output_tokens=None,
                estimated_cost_usd=estimated_cost,
                actual_cost_usd=None,
            )
        else:
            assets = list(
                database.scalars(
                    select(models.ClientAsset.reference)
                    .where(models.ClientAsset.client_id == client.id)
                    .order_by(models.ClientAsset.added_at, models.ClientAsset.id)
                )
            )
            profile, missing, conflicts, processing_status = interpretation_service.interpret(
                intake, client.business_name, assets
            )
    except OpenAIInterpretationError as error:
        raise HTTPException(status_code=503 if error.retryable else 502, detail=error.code) from error
    record = models.InterpretationProposal(
        intake_id=intake.id,
        client_id=intake.client_id,
        profile_data=profile,
        missing_information=missing,
        conflicting_information=conflicts,
        processing_status=processing_status,
        processed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    database.add(record)
    database.commit()
    database.refresh(record)
    database.add(
        models.ProfileVersion(
            source_proposal_id=record.id,
            intake_id=record.intake_id,
            client_id=record.client_id,
            version_number=1,
            profile_data=record.profile_data,
        )
    )
    database.commit()
    return record


@router.get("/interpretations/{proposal_id}", response_model=schemas.InterpretationRead)
def read_interpretation(proposal_id: str, database: Session = Depends(get_database)) -> models.InterpretationProposal:
    record = database.get(models.InterpretationProposal, proposal_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Interpretation proposal not found")
    return record


@router.get("/profile-versions/{version_id}", response_model=schemas.ProfileVersionRead)
def read_profile_version(version_id: str, database: Session = Depends(get_database)) -> models.ProfileVersion:
    record = database.get(models.ProfileVersion, version_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Profile version not found")
    return record


@router.get("/interpretations/{proposal_id}/versions", response_model=list[schemas.ProfileVersionRead])
def list_profile_versions(proposal_id: str, database: Session = Depends(get_database)) -> list[models.ProfileVersion]:
    if database.get(models.InterpretationProposal, proposal_id) is None:
        raise HTTPException(status_code=404, detail="Interpretation proposal not found")
    return list(
        database.scalars(
            select(models.ProfileVersion)
            .where(models.ProfileVersion.source_proposal_id == proposal_id)
            .order_by(models.ProfileVersion.version_number)
        )
    )


@router.post("/profile-versions/{version_id}/decision", response_model=schemas.ProfileVersionRead)
def decide_profile_version(
    version_id: str,
    decision: schemas.ProfileDecision,
    database: Session = Depends(get_database),
) -> models.ProfileVersion:
    version = database.get(models.ProfileVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Profile version not found")
    if version.status != "pending":
        raise HTTPException(status_code=409, detail="This profile version has already been decided")
    client = database.get(models.Client, version.client_id)
    if client is None:
        raise HTTPException(status_code=409, detail="Profile version client is missing")
    if client.archived_at is not None or client.status == "archived":
        raise HTTPException(status_code=409, detail="Archived clients cannot receive profile approvals")
    if decision.decision == "reject" and not decision.reason:
        raise HTTPException(status_code=422, detail="A rejection reason is required")
    proposal = database.get(models.InterpretationProposal, version.source_proposal_id)
    if decision.decision == "approve" and proposal is not None:
        if proposal.missing_information or proposal.conflicting_information:
            raise HTTPException(
                status_code=409,
                detail="Resolve missing and conflicting information before approving the profile",
            )

    version.status = "approved" if decision.decision == "approve" else "rejected"
    version.decision_maker = decision.decision_maker
    version.decision_reason = decision.reason
    version.decided_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if version.status == "approved":
        official = database.scalar(
            select(models.OfficialProfile).where(models.OfficialProfile.client_id == version.client_id)
        )
        if official is None:
            database.add(models.OfficialProfile(
                client_id=version.client_id,
                approved_version_id=version.id,
                profile_data=version.profile_data,
                approved_by=decision.decision_maker,
            ))
        else:
            official.approved_version_id = version.id
            official.profile_data = version.profile_data
            official.approved_by = decision.decision_maker
            official.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        run = database.scalar(
            select(models.OnboardingAutomationRun).where(
                models.OnboardingAutomationRun.intake_id == version.intake_id
            )
        )
        if run is not None:
            from app.onboarding_automation import schedule_run

            schedule_run(database, run, immediate=True)
    database.commit()
    database.refresh(version)
    return version


@router.post("/profile-versions/{version_id}/correct", response_model=schemas.ProfileVersionRead, status_code=status.HTTP_201_CREATED)
def correct_profile_version(
    version_id: str,
    correction: schemas.ProfileCorrection,
    database: Session = Depends(get_database),
) -> models.ProfileVersion:
    previous = database.get(models.ProfileVersion, version_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="Profile version not found")
    client = database.get(models.Client, previous.client_id)
    if client is None or client.archived_at is not None or client.status == "archived":
        raise HTTPException(status_code=409, detail="Archived clients cannot receive profile corrections")
    if previous.status != "rejected":
        raise HTTPException(status_code=409, detail="Only a rejected profile version can be corrected")
    next_number = database.scalar(
        select(func.max(models.ProfileVersion.version_number)).where(
            models.ProfileVersion.source_proposal_id == previous.source_proposal_id
        )
    ) or previous.version_number
    version = models.ProfileVersion(
        source_proposal_id=previous.source_proposal_id,
        intake_id=previous.intake_id,
        client_id=previous.client_id,
        version_number=next_number + 1,
        profile_data=correction.profile_data,
    )
    database.add(version)
    database.commit()
    database.refresh(version)
    return version


@router.get("/clients/{client_id}/official-profile", response_model=schemas.OfficialProfileRead)
def read_official_profile(client_id: str, database: Session = Depends(get_database)) -> models.OfficialProfile:
    if database.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    record = database.scalar(select(models.OfficialProfile).where(models.OfficialProfile.client_id == client_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Official profile not found")
    return record
