"""Application entry point.

This is the first file FastAPI reads when the app starts.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4
from datetime import datetime, timedelta
import os

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy import func, select
from fastapi.staticfiles import StaticFiles

from app.database import create_database
from app import models
from app.database import SessionLocal
from app.routes import agency, ai_costs, auth, billing, browser_execution, clients, codex_packets, daily_plans, dashboard, fulfillment, github_repositories, google_business_profile, google_oauth, health_checks, intake, interpretations, jobs, metrics, notifications, onboarding_automation, prompts, reports, search_console, slack, tasks, verifications, website_execution, website_generation, website_metrics, websites
from app.security import enforce_request_security
from app.readiness_service import build_readiness


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Production schema changes are explicit and signed. Local/test databases
    # retain their convenient create-all bootstrap behavior.
    if os.getenv("VERCEL_ENV", "").strip().casefold() not in {"production", "preview"}:
        create_database()
    yield


# `app` is the FastAPI application object.
# Uvicorn looks for this name when it starts the server.
app = FastAPI(title="Max", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def security_headers(request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID", "").strip()[:80] or uuid4().hex
    response = await enforce_request_security(request, call_next)
    response.headers.setdefault("X-Request-ID", request.state.request_id)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://accounts.google.com")
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


LANDING_TEMPLATE_PATH = Path(__file__).parent / "templates" / "public_landing.html"


@app.get("/", include_in_schema=False)
def public_landing() -> HTMLResponse:
    """Describe the project at the browser root.

    The application routes need an owner session and a configured database, so
    on a public deployment they correctly refuse to serve anything. That left
    the root as a bare 503. This page explains what the system is and stays
    entirely static: it reads no database, no provider, and no client record.
    """
    return HTMLResponse(LANDING_TEMPLATE_PATH.read_text(encoding="utf-8"))


# `@app.get("/health")` means:
# when someone sends a GET request to /health,
# run the function below.
@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    # Keep a health check simple and predictable.
    # Returning a fixed response makes it easy to test.
    from app.database import SessionLocal

    with SessionLocal() as database:
        database.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/health/details", tags=["system"])
def health_details(request: Request) -> dict:
    """Return safe operational signals without exposing client data or secrets."""
    now = datetime.utcnow()
    with SessionLocal() as database:
        database.execute(text("SELECT 1"))
        failed_jobs = database.scalar(
            select(func.count()).select_from(models.ScheduledJob).where(models.ScheduledJob.last_status == "failed")
        ) or 0
        failed_job_ids = list(
            database.scalars(
                select(models.ScheduledJob.id)
                .where(models.ScheduledJob.last_status == "failed")
                .order_by(models.ScheduledJob.last_run_at.desc(), models.ScheduledJob.id)
                .limit(20)
            )
        )
        running_jobs = database.scalar(
            select(func.count()).select_from(models.ScheduledJob).where(
                models.ScheduledJob.enabled.is_(True), models.ScheduledJob.last_status == "running"
            )
        ) or 0
        stale_jobs = database.scalar(
            select(func.count()).select_from(models.ScheduledJob).where(
                models.ScheduledJob.enabled.is_(True),
                models.ScheduledJob.last_status == "running",
                models.ScheduledJob.last_started_at < now - timedelta(minutes=30),
            )
        ) or 0
        stale_job_ids = list(
            database.scalars(
                select(models.ScheduledJob.id)
                .where(
                    models.ScheduledJob.enabled.is_(True),
                    models.ScheduledJob.last_status == "running",
                    models.ScheduledJob.last_started_at < now - timedelta(minutes=30),
                )
                .order_by(models.ScheduledJob.last_started_at, models.ScheduledJob.id)
                .limit(20)
            )
        )
        due_jobs = database.scalar(
            select(func.count()).select_from(models.ScheduledJob).where(
                models.ScheduledJob.enabled.is_(True), models.ScheduledJob.next_run_at <= now
            )
        ) or 0
        stale_runs = database.scalar(
            select(func.count()).select_from(models.OnboardingAutomationRun).where(
                models.OnboardingAutomationRun.status.in_({"queued", "processing", "retrying"}),
                models.OnboardingAutomationRun.updated_at < now - timedelta(minutes=30),
            )
        ) or 0
        stale_run_ids = list(
            database.scalars(
                select(models.OnboardingAutomationRun.id)
                .where(
                    models.OnboardingAutomationRun.status.in_({"queued", "processing", "retrying"}),
                    models.OnboardingAutomationRun.updated_at < now - timedelta(minutes=30),
                )
                .order_by(models.OnboardingAutomationRun.updated_at, models.OnboardingAutomationRun.id)
                .limit(20)
            )
        )
    status = "ok" if not stale_runs and not stale_jobs and not failed_jobs else "degraded"
    alerts = []
    if failed_jobs:
        alerts.append({
            "code": "scheduled_jobs_failed",
            "severity": "high",
            "record_ids": failed_job_ids,
            "remediation": "Inspect the scheduled job error, restore provider access, and rerun the job.",
        })
    if stale_jobs:
        alerts.append({
            "code": "scheduled_jobs_stale",
            "severity": "critical",
            "record_ids": stale_job_ids,
            "remediation": "Inspect the worker lease and recover or disable the stale scheduled run.",
        })
    if stale_runs:
        alerts.append({
            "code": "onboarding_runs_stale",
            "severity": "high",
            "record_ids": stale_run_ids,
            "remediation": "Inspect the onboarding worker and resume or retry the stale run.",
        })
    return {
        "status": status,
        "database": "ok",
        "scheduler": {
            "due_jobs": due_jobs,
            "failed_jobs": failed_jobs,
            "running_jobs": running_jobs,
            "stale_jobs": stale_jobs,
        },
        "onboarding": {"stale_runs": stale_runs},
        "alerts": alerts,
        "request_id": getattr(request.state, "request_id", None),
    }


@app.get("/health/readiness", tags=["system"])
def health_readiness(profile: str = "core") -> dict:
    """Report deployment blockers without exposing configured values or secrets."""
    if profile not in {"core", "full"}:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="unsupported_readiness_profile")
    with SessionLocal() as database:
        return build_readiness(database, profile)


app.include_router(clients.router)
app.include_router(agency.router)
app.include_router(auth.router)
app.include_router(billing.router)
app.include_router(intake.router)
app.include_router(interpretations.router)
app.include_router(jobs.router)
app.include_router(dashboard.router)
app.include_router(metrics.router)
app.include_router(health_checks.router)
app.include_router(tasks.router)
app.include_router(daily_plans.router)
app.include_router(codex_packets.router)
app.include_router(github_repositories.router)
app.include_router(search_console.router)
app.include_router(ai_costs.router)
app.include_router(fulfillment.router)
app.include_router(verifications.router)
app.include_router(reports.router)
app.include_router(notifications.router)
app.include_router(onboarding_automation.router)
app.include_router(prompts.router)
app.include_router(google_business_profile.router)
app.include_router(website_execution.router)
app.include_router(browser_execution.router)
app.include_router(website_generation.router)
app.include_router(slack.router)
app.include_router(websites.router)
app.include_router(website_metrics.router)
app.include_router(google_oauth.router)
