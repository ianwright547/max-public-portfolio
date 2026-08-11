"""Persisted background-job definitions and a deterministic due-job runner."""

from datetime import datetime
import hmac
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_database
from app.job_service import run_due_jobs
from app.migration_service import run_production_migrations
from app.auth_service import auth_is_configured, auth_is_required

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _authorized_scheduler_request(request: Request, *, require_secret: bool = False) -> None:
    """Accept Max's manual scheduler header or Vercel Cron's bearer token."""
    job_secret = os.getenv("JOB_RUNNER_SECRET", "").strip()
    cron_secret = os.getenv("CRON_SECRET", "").strip()
    provided_job_secret = request.headers.get("X-Max-Job-Secret", "")
    authorization = request.headers.get("Authorization", "")
    valid_job_secret = bool(job_secret) and hmac.compare_digest(provided_job_secret, job_secret)
    valid_cron_secret = bool(cron_secret) and hmac.compare_digest(
        authorization, f"Bearer {cron_secret}"
    )
    if valid_job_secret or valid_cron_secret:
        return
    if not require_secret and not job_secret and not cron_secret:
        # The no-secret learning mode is useful for local development, but it
        # must never turn an authenticated production deployment into an
        # unauthenticated scheduler. Readiness catches the missing secret; this
        # endpoint also fails closed so a misconfigured deployment cannot be
        # triggered by anyone who can reach its public URL.
        production = os.getenv("VERCEL_ENV", "").strip().casefold() in {"production", "preview"}
        if not production and not auth_is_configured() and not auth_is_required():
            return
    raise HTTPException(status_code=401, detail="job_runner_unauthorized")


@router.post("", response_model=schemas.ScheduledJobRead, status_code=status.HTTP_201_CREATED)
def create_job(job: schemas.ScheduledJobCreate, database: Session = Depends(get_database)) -> models.ScheduledJob:
    if job.client_id and database.get(models.Client, job.client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    if job.job_type in {"health_check", "search_console_sync", "daily_client_plan"} and not job.client_id:
        raise HTTPException(status_code=422, detail=f"{job.job_type} requires client_id")
    existing = database.scalar(select(models.ScheduledJob).where(models.ScheduledJob.job_key == job.job_key))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Job key already exists")
    parameters = dict(job.parameters)
    if job.job_type == "daily_client_plan":
        if parameters.get("depth", "simple") not in {"simple", "in_depth"}:
            raise HTTPException(status_code=422, detail="daily_client_plan depth must be simple or in_depth")
        if parameters.get("focus", "all") not in {"all", "seo", "fulfillment", "reporting"}:
            raise HTTPException(status_code=422, detail="daily_client_plan focus is invalid")
        if not isinstance(parameters.get("create_report", False), bool):
            raise HTTPException(status_code=422, detail="daily_client_plan create_report must be boolean")
        if not isinstance(parameters.get("create_tasks", False), bool):
            raise HTTPException(status_code=422, detail="daily_client_plan create_tasks must be boolean")
        parameters = {
            "depth": parameters.get("depth", "simple"),
            "focus": parameters.get("focus", "all"),
            "create_report": parameters.get("create_report", False),
            "create_tasks": parameters.get("create_tasks", False),
            "report_type": parameters.get("report_type", "internal"),
        }
        if parameters["report_type"] not in {"internal", "client"}:
            raise HTTPException(status_code=422, detail="daily_client_plan report_type is invalid")
    else:
        parameters = {}
    record = models.ScheduledJob(
        **job.model_dump(exclude_none=True, exclude={"next_run_at", "parameters"}),
        parameters=parameters,
        next_run_at=job.next_run_at or datetime.utcnow(),
    )
    database.add(record)
    database.commit()
    database.refresh(record)
    return record


@router.get("", response_model=list[schemas.ScheduledJobRead])
def list_jobs(database: Session = Depends(get_database)) -> list[models.ScheduledJob]:
    return list(database.scalars(select(models.ScheduledJob).order_by(models.ScheduledJob.next_run_at)))


@router.post("/run-due", response_model=list[schemas.ScheduledJobRunRead])
def run_due(request: Request, database: Session = Depends(get_database)) -> list[dict]:
    """Run due jobs only when the configured scheduler secret matches.

    Local learning mode remains usable when no secret is configured. Production
    must set JOB_RUNNER_SECRET before exposing a scheduler URL.
    """
    _authorized_scheduler_request(request)
    return run_due_jobs(database)


@router.get("/run-due", response_model=list[schemas.ScheduledJobRunRead])
def run_due_from_vercel_cron(
    request: Request, database: Session = Depends(get_database)
) -> list[dict]:
    """Run due jobs from Vercel Cron, which invokes configured paths with GET."""
    _authorized_scheduler_request(request, require_secret=True)
    return run_due_jobs(database)


@router.get("/provider-health")
def provider_health_sweep(request: Request, database: Session = Depends(get_database)) -> dict:
    """Run a secret-protected, read-only provider sweep for active clients."""
    _authorized_scheduler_request(request, require_secret=True)
    from app.client_provider_verification import sweep_active_clients

    result = sweep_active_clients(database)
    database.commit()
    return result


@router.post("/migrate")
def migrate_database(request: Request) -> dict[str, str]:
    """Apply repository migrations using runtime-only production credentials."""
    _authorized_scheduler_request(request, require_secret=True)
    return run_production_migrations()
