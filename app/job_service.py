"""Small idempotent runner for persisted Max background jobs."""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, update, or_
from sqlalchemy.orm import Session

from app import models


def run_due_jobs(database: Session, now: Optional[datetime] = None) -> list[dict]:
    current_time = now or datetime.utcnow()
    stale_before = current_time - timedelta(minutes=30)
    jobs = list(
        database.scalars(
            select(models.ScheduledJob)
            .where(
                models.ScheduledJob.enabled.is_(True),
                models.ScheduledJob.next_run_at <= current_time,
                or_(
                    models.ScheduledJob.last_status != "running",
                    models.ScheduledJob.last_started_at.is_(None),
                    models.ScheduledJob.last_started_at < stale_before,
                ),
            )
            .order_by(models.ScheduledJob.next_run_at, models.ScheduledJob.id)
        )
    )
    results: list[dict] = []
    for job in jobs:
        claimed = database.execute(
            update(models.ScheduledJob)
            .where(
                models.ScheduledJob.id == job.id,
                models.ScheduledJob.enabled.is_(True),
                models.ScheduledJob.next_run_at <= current_time,
                or_(
                    models.ScheduledJob.last_status != "running",
                    models.ScheduledJob.last_started_at.is_(None),
                    models.ScheduledJob.last_started_at < stale_before,
                ),
            )
            .values(last_status="running", last_started_at=current_time)
        ).rowcount
        database.commit()
        if claimed != 1:
            continue
        database.refresh(job)
        started_at = current_time
        status = "completed"
        error = None
        try:
            if job.job_type == "health_check":
                if not job.client_id:
                    raise ValueError("health_check_requires_client_id")
                from app.routes.health_checks import run_health_check

                run_health_check(database, job.client_id, "available")
            elif job.job_type == "website_metrics_sync":
                from app.website_analytics import sync_website_metrics

                sync_website_metrics(database, 30)
            elif job.job_type == "search_console_sync":
                if not job.client_id:
                    raise ValueError("search_console_sync_requires_client_id")
                from app.routes.search_console import sync_search_console
                from app.schemas import SearchConsoleSyncRequest

                end_date = current_time.date()
                sync_search_console(
                    job.client_id,
                    SearchConsoleSyncRequest(
                        start_date=end_date - timedelta(days=28),
                        end_date=end_date,
                    ),
                    database,
                )
            elif job.job_type == "daily_client_plan":
                if not job.client_id:
                    raise ValueError("daily_client_plan_requires_client_id")
                from app.daily_planning_service import generate_daily_plans
                from app.notification_service import NotificationEvent, deliver_notification

                client = database.get(models.Client, job.client_id)
                if client is None or client.archived_at is not None:
                    job.enabled = False
                else:
                    parameters = job.parameters or {}
                    # A recurring fulfillment plan may create approval tasks.
                    # Probe the exact saved providers first so a stale or
                    # mismatched connection cannot silently produce work that
                    # the agency cannot execute. Reporting-only plans still
                    # run and preserve their access limitations in the report.
                    if parameters.get("create_tasks") or parameters.get("focus") == "fulfillment":
                        from app.client_provider_verification import verify_client_providers

                        provider_probe = verify_client_providers(database, client.id)
                        if provider_probe["status"] == "failed":
                            failed_codes = ", ".join(
                                str(item.get("code") or "provider_probe_failed")
                                for item in provider_probe["results"]
                                if item.get("status") == "failed"
                            )
                            # Preserve the provider status/audit evidence before
                            # the scheduler records the blocked job attempt.
                            database.commit()
                            raise ValueError(f"client_provider_verification_failed:{failed_codes[:180]}")
                    plans = generate_daily_plans(
                        database,
                        depth=parameters.get("depth", "simple"),
                        focus=parameters.get("focus", "all"),
                        created_by="scheduled daily planner",
                        client=client,
                        plan_date=current_time.date(),
                        create_tasks=bool(parameters.get("create_tasks", False)),
                    )
                    plan = plans[0]
                    top_items = [item["title"] for item in plan.items[:3]]
                    deliver_notification(
                        database,
                        NotificationEvent(
                            event_key=f"daily-plan:{plan.client_id}:{plan.plan_date.isoformat()}",
                            client_id=plan.client_id,
                            category="scheduled_report_available",
                            importance="medium",
                            explanation=(
                                f"Today's evidence-backed work plan is ready: "
                                + "; ".join(top_items)
                            )[:600],
                            requested_action=(
                                "Ask `today's tasks for this client` for the complete plan, or "
                                "`in-depth SEO plan for this client` to refresh live evidence first."
                            ),
                            related_record_type="daily_client_plan",
                            related_record_id=plan.id,
                        ),
                    )
                    if parameters.get("create_report"):
                        from app.routes.reports import create_report_record
                        from app.schemas import ReportCreate

                        report_type = (job.parameters or {}).get("report_type", "internal")
                        create_report_record(
                            database,
                            client.id,
                            ReportCreate(
                                report_type=report_type,
                                period_start=current_time.date().replace(day=1),
                                period_end=current_time.date(),
                                generated_by="scheduled daily planner",
                                generation_reason="scheduled",
                                update_mode=parameters.get("depth", "simple"),
                            ),
                        )
            elif job.job_type == "onboarding_automation":
                from app.onboarding_automation import process_onboarding_run

                run_id = job.job_key.removeprefix("onboarding:")
                run = process_onboarding_run(database, run_id)
                if run.status in {
                    "awaiting_profile_approval",
                    "awaiting_connection_review",
                    "ready_for_fulfillment",
                    "blocked",
                    "completed",
                }:
                    job.enabled = False
            else:
                raise ValueError("unsupported_job_type")
        except Exception as caught:
            database.rollback()
            job = database.get(models.ScheduledJob, job.id)
            if job is None:
                continue
            status = "failed"
            error = type(caught).__name__ + ": " + str(caught)[:240]
        finished_at = datetime.utcnow()
        job.last_run_at = current_time
        job.last_started_at = None
        job.last_status = status
        job.last_error = error
        job.last_duration_seconds = max(0.0, (finished_at - started_at).total_seconds())
        if status == "failed":
            job.consecutive_failures += 1
            delay = min(job.interval_minutes * (2 ** min(job.consecutive_failures, 4)), 24 * 60)
        else:
            job.consecutive_failures = 0
            delay = job.interval_minutes
        if job.enabled:
            job.next_run_at = current_time + timedelta(minutes=delay)
        if status == "failed" and job.client_id:
            from app.notification_service import notify_scheduled_job_failure

            notify_scheduled_job_failure(database, job, error or "unknown scheduler error")
        database.add(job)
        database.commit()
        results.append({"job_id": job.id, "job_key": job.job_key, "status": status, "error": error})
    return results
