"""Owner-facing APIs for durable automatic onboarding and match review."""

from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.audit import record_event
from app.database import get_database
from app.github_service import GitHubAppAdapter, GitHubIntegrationError
from app.onboarding_automation import (
    OnboardingStepError,
    _analytics_rows,
    _save_analytics,
    _save_github,
    _save_vercel,
    backfill_onboarding_runs,
    queue_onboarding_run,
    schedule_run,
)
from app.vercel_service import VercelAdapter, VercelIntegrationError


router = APIRouter(tags=["onboarding automation"])


def _client(database: Session, client_id: str) -> models.Client:
    client = database.get(models.Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.post(
    "/clients/{client_id}/onboarding-automation",
    response_model=schemas.OnboardingAutomationRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_onboarding_automation(
    client_id: str,
    database: Session = Depends(get_database),
) -> models.OnboardingAutomationRun:
    _client(database, client_id)
    try:
        run, _reused = queue_onboarding_run(database, client_id, immediate=True)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    database.commit()
    database.refresh(run)
    return run


@router.get(
    "/clients/{client_id}/onboarding-automation",
    response_model=schemas.OnboardingAutomationRunRead,
)
def read_onboarding_automation(
    client_id: str,
    database: Session = Depends(get_database),
) -> models.OnboardingAutomationRun:
    _client(database, client_id)
    intake = database.scalar(
        select(models.Intake)
        .where(models.Intake.client_id == client_id)
        .order_by(models.Intake.submitted_at.desc(), models.Intake.id.desc())
    )
    if intake is None:
        raise HTTPException(status_code=404, detail="Onboarding automation has not been queued")
    run = database.scalar(
        select(models.OnboardingAutomationRun).where(
            models.OnboardingAutomationRun.client_id == client_id,
            models.OnboardingAutomationRun.intake_id == intake.id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Onboarding automation has not been queued")
    return run


@router.get(
    "/clients/{client_id}/connection-candidates",
    response_model=list[schemas.ConnectionCandidateRead],
)
def list_connection_candidates(
    client_id: str,
    database: Session = Depends(get_database),
) -> list[models.ConnectionCandidate]:
    _client(database, client_id)
    return list(
        database.scalars(
            select(models.ConnectionCandidate)
            .where(models.ConnectionCandidate.client_id == client_id)
            .order_by(models.ConnectionCandidate.created_at.desc(), models.ConnectionCandidate.id.desc())
        )
    )


def _approve_candidate(database: Session, candidate: models.ConnectionCandidate) -> str:
    data = candidate.connection_data
    if candidate.provider == "vercel":
        try:
            project = VercelAdapter().get_project(candidate.external_identifier)
        except VercelIntegrationError as error:
            raise HTTPException(status_code=503 if error.retryable else 409, detail=error.code) from error
        if project.project_id != data.get("external_project_id"):
            raise HTTPException(status_code=409, detail="vercel_candidate_changed")
        connection = database.scalar(select(models.WebsiteConnection).where(models.WebsiteConnection.client_id == candidate.client_id))
        connection = connection or _save_vercel(database, candidate.client_id, project)
        return connection.id
    if candidate.provider == "github":
        try:
            repository = GitHubAppAdapter().get_repository(data.get("owner", ""), data.get("repository_name", ""))
        except GitHubIntegrationError as error:
            raise HTTPException(status_code=503 if error.retryable else 409, detail=error.code) from error
        if repository.html_url.rstrip("/").casefold() != str(data.get("repository_url", "")).rstrip("/").casefold():
            raise HTTPException(status_code=409, detail="github_candidate_changed")
        connection = database.scalar(select(models.GitHubRepositoryConnection).where(models.GitHubRepositoryConnection.client_id == candidate.client_id))
        connection = connection or _save_github(database, candidate.client_id, repository)
        return connection.id
    if candidate.provider == "website_analytics":
        tracker_sites = [str(site) for site in data.get("tracker_sites", [])]
        available = {str(row.get("site", "")) for row in _analytics_rows()}
        if not tracker_sites or not set(tracker_sites).issubset(available):
            raise HTTPException(status_code=409, detail="analytics_candidate_changed")
        connection = database.scalar(select(models.WebsiteAnalyticsConnection).where(models.WebsiteAnalyticsConnection.client_id == candidate.client_id))
        connection = connection or _save_analytics(database, candidate.client_id, tracker_sites, source="owner_approved_discovery")
        return connection.id
    raise HTTPException(status_code=422, detail="Unsupported connection provider")


@router.post(
    "/connection-candidates/{candidate_id}/decision",
    response_model=schemas.ConnectionCandidateRead,
)
def decide_connection_candidate(
    candidate_id: str,
    decision: schemas.ConnectionCandidateDecision,
    database: Session = Depends(get_database),
) -> models.ConnectionCandidate:
    candidate = database.get(models.ConnectionCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Connection candidate not found")
    if candidate.status != "pending":
        raise HTTPException(status_code=409, detail="Connection candidate has already been decided")
    run = database.get(models.OnboardingAutomationRun, candidate.run_id)
    if run is None or run.client_id != candidate.client_id:
        raise HTTPException(status_code=409, detail="Connection candidate is not linked to a valid onboarding run")
    if decision.decision == "reject" and not (decision.reason or "").strip():
        raise HTTPException(status_code=422, detail="A rejection reason is required")
    if decision.decision == "approve":
        try:
            connection_id = _approve_candidate(database, candidate)
        except OnboardingStepError as error:
            raise HTTPException(status_code=409, detail=error.code) from error
        steps = dict(run.steps or {})
        steps[candidate.provider] = {"status": "completed", "connection_id": connection_id, "match": "owner_approved"}
        run.steps = steps
        candidate.status = "approved"
        siblings = list(
            database.scalars(
                select(models.ConnectionCandidate).where(
                    models.ConnectionCandidate.run_id == run.id,
                    models.ConnectionCandidate.provider == candidate.provider,
                    models.ConnectionCandidate.id != candidate.id,
                    models.ConnectionCandidate.status == "pending",
                )
            )
        )
        for sibling in siblings:
            sibling.status = "rejected"
            sibling.decided_by = decision.decided_by
            sibling.decision_reason = "Superseded by the approved provider match"
            sibling.decided_at = datetime.utcnow()
    else:
        candidate.status = "rejected"
    candidate.decided_by = decision.decided_by
    candidate.decision_reason = decision.reason
    candidate.decided_at = datetime.utcnow()
    record_event(database, "connection_candidate_decided", actor=decision.decided_by, client_id=candidate.client_id, record_type="connection_candidate", record_id=candidate.id, details={"provider": candidate.provider, "decision": decision.decision})
    database.flush()
    pending = database.scalar(select(models.ConnectionCandidate.id).where(models.ConnectionCandidate.run_id == run.id, models.ConnectionCandidate.status == "pending"))
    provider_approved = database.scalar(select(models.ConnectionCandidate.id).where(models.ConnectionCandidate.run_id == run.id, models.ConnectionCandidate.provider == candidate.provider, models.ConnectionCandidate.status == "approved"))
    if pending is None and provider_approved is None:
        run.status = "blocked"
        run.current_step = candidate.provider
        run.last_error = f"{candidate.provider}_match_rejected"
    elif pending is None:
        schedule_run(database, run, immediate=True)
    database.commit()
    database.refresh(candidate)
    return candidate


@router.post(
    "/onboarding-automation/backfill",
    response_model=schemas.OnboardingBackfillRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def backfill_onboarding_automation(
    database: Session = Depends(get_database),
) -> dict:
    queued, reused = backfill_onboarding_runs(database)
    return {"queued_client_ids": queued, "reused_client_ids": reused}


@router.post("/dashboard/clients/{client_id}/onboarding-automation", response_class=RedirectResponse)
def dashboard_start_onboarding_automation(
    client_id: str,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    start_onboarding_automation(client_id, database)
    return RedirectResponse(url=f"/dashboard/clients/{client_id}?notice=Automatic+onboarding+queued", status_code=303)


@router.post("/dashboard/connection-candidates/{candidate_id}/decision", response_class=RedirectResponse)
def dashboard_decide_connection_candidate(
    candidate_id: str,
    decision: str = Form(...),
    decided_by: str = Form(...),
    reason: str = Form(""),
    database: Session = Depends(get_database),
) -> RedirectResponse:
    candidate = decide_connection_candidate(
        candidate_id,
        schemas.ConnectionCandidateDecision(
            decision=decision,
            decided_by=decided_by,
            reason=reason or None,
        ),
        database,
    )
    return RedirectResponse(url=f"/dashboard/clients/{candidate.client_id}?notice=Connection+decision+saved", status_code=303)
