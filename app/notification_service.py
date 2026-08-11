"""Meaningful event rules and replaceable notification delivery for Phase 12."""

import os
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.metric_rules import comparison_number


MEANINGFUL_CHANGE_PERCENT = 25.0
COST_NOTIFICATION_THRESHOLD = float(os.getenv("MAX_COST_NOTIFICATION_THRESHOLD", "5.00"))

ALLOWED_CATEGORIES = {
    "approval_required",
    "critical_health_issue",
    "task_failure",
    "verification_failure",
    "missing_required_access",
    "cost_threshold_exceeded",
    "meaningful_performance_change",
    "scheduled_report_available",
    "scheduled_job_failure",
}


@dataclass(frozen=True)
class NotificationEvent:
    event_key: str
    client_id: str
    category: str
    importance: str
    explanation: str
    requested_action: str
    related_record_type: str
    related_record_id: str


class InternalNotificationDelivery:
    """Persist events in SQLite; a Slack delivery can implement this same method."""

    def deliver(
        self,
        database: Session,
        event: NotificationEvent,
    ) -> tuple[models.Notification, bool]:
        if event.category not in ALLOWED_CATEGORIES:
            raise ValueError(f"Unsupported notification category: {event.category}")
        existing = database.scalar(
            select(models.Notification).where(models.Notification.event_key == event.event_key)
        )
        if existing is not None:
            return existing, False
        notification = models.Notification(**event.__dict__)
        database.add(notification)
        database.flush()
        return notification, True


internal_delivery = InternalNotificationDelivery()


def deliver_notification(
    database: Session,
    event: NotificationEvent,
) -> tuple[models.Notification, bool]:
    notification, created = internal_delivery.deliver(database, event)
    if created:
        # Slack is a secondary delivery surface. The internal database record
        # remains the source of truth when Slack is missing or temporarily down.
        from app.slack_service import deliver_saved_notification

        deliver_saved_notification(database, notification)
    return notification, created


def notify_task_approval(database: Session, task: models.Task) -> None:
    deliver_notification(
        database,
        NotificationEvent(
            event_key=f"approval-required:task:{task.id}",
            client_id=task.client_id,
            category="approval_required",
            importance="medium",
            explanation=f'Task proposal "{task.title}" requires an agency-owner decision.',
            requested_action="Review the evidence and approve or reject the task.",
            related_record_type="task",
            related_record_id=task.id,
        ),
    )


def notify_health_finding(database: Session, finding: models.Finding) -> None:
    if finding.severity == "critical":
        deliver_notification(
            database,
            NotificationEvent(
                event_key=f"critical-health:finding:{finding.id}",
                client_id=finding.client_id,
                category="critical_health_issue",
                importance="critical",
                explanation=finding.explanation,
                requested_action=finding.recommended_action,
                related_record_type="finding",
                related_record_id=finding.id,
            ),
        )
    if finding.rule_key.startswith("integration_access:"):
        deliver_notification(
            database,
            NotificationEvent(
                event_key=f"missing-access:finding:{finding.id}",
                client_id=finding.client_id,
                category="missing_required_access",
                importance="high",
                explanation=finding.explanation,
                requested_action=finding.recommended_action,
                related_record_type="finding",
                related_record_id=finding.id,
            ),
        )


def notify_execution_result(database: Session, execution: models.FulfillmentExecution, task: models.Task) -> None:
    if execution.status == "failed":
        deliver_notification(
            database,
            NotificationEvent(
                event_key=f"task-failure:execution:{execution.id}",
                client_id=execution.client_id,
                category="task_failure",
                importance="high",
                explanation=execution.error_message or f'Task "{task.title}" failed.',
                requested_action="Review the failure evidence before approving a correction or retry.",
                related_record_type="execution",
                related_record_id=execution.id,
            ),
        )
    if execution.estimated_cost > COST_NOTIFICATION_THRESHOLD:
        deliver_notification(
            database,
            NotificationEvent(
                event_key=f"cost-threshold:execution:{execution.id}",
                client_id=execution.client_id,
                category="cost_threshold_exceeded",
                importance="high",
                explanation=(
                    f"Estimated execution cost ${execution.estimated_cost:.2f} exceeded the "
                    f"${COST_NOTIFICATION_THRESHOLD:.2f} notification threshold."
                ),
                requested_action="Review the recorded cost and confirm whether further work should continue.",
                related_record_type="execution",
                related_record_id=execution.id,
            ),
        )


def notify_verification_failure(
    database: Session,
    decision: models.ExecutionVerification,
) -> None:
    if decision.outcome != "verification_failed":
        return
    deliver_notification(
        database,
        NotificationEvent(
            event_key=f"verification-failure:decision:{decision.id}",
            client_id=decision.client_id,
            category="verification_failure",
            importance="high",
            explanation=decision.explanation,
            requested_action="Review the failed checks and return the task for correction.",
            related_record_type="verification",
            related_record_id=decision.id,
        ),
    )


def meaningful_metric_change(
    database: Session,
    snapshot: models.MetricSnapshot,
) -> Optional[NotificationEvent]:
    if snapshot.metric_name == "last_google_post_date":
        return None
    history = list(
        database.scalars(
            select(models.MetricSnapshot)
            .where(
                models.MetricSnapshot.client_id == snapshot.client_id,
                models.MetricSnapshot.metric_name == snapshot.metric_name,
            )
            .order_by(
                models.MetricSnapshot.measurement_period.desc(),
                models.MetricSnapshot.recorded_at.desc(),
                models.MetricSnapshot.id.desc(),
            )
        )
    )
    latest_by_period = {}
    for item in history:
        latest_by_period.setdefault(item.measurement_period, item)
    periods = sorted(latest_by_period, reverse=True)
    if len(periods) < 2 or latest_by_period[periods[0]].id != snapshot.id:
        return None
    current = comparison_number(snapshot.metric_name, snapshot.value)
    previous_snapshot = latest_by_period[periods[1]]
    previous = comparison_number(previous_snapshot.metric_name, previous_snapshot.value)
    if previous == 0:
        return None
    percent = round((current - previous) / previous * 100, 1)
    if abs(percent) < MEANINGFUL_CHANGE_PERCENT:
        return None
    direction = "increased" if percent > 0 else "decreased"
    return NotificationEvent(
        event_key=(
            f"meaningful-change:metric:{snapshot.client_id}:"
            f"{snapshot.metric_name}:{snapshot.measurement_period}"
        ),
        client_id=snapshot.client_id,
        category="meaningful_performance_change",
        importance="medium" if percent > 0 else "high",
        explanation=(
            f"{snapshot.metric_name.replace('_', ' ').title()} {direction} by "
            f"{abs(percent):.1f}% from {previous_snapshot.measurement_period} to "
            f"{snapshot.measurement_period}. Source: {snapshot.source_type}."
        ),
        requested_action="Review the saved comparison and decide whether follow-up is needed.",
        related_record_type="metric_snapshot",
        related_record_id=snapshot.id,
    )


def notify_metric_change(database: Session, snapshot: models.MetricSnapshot) -> None:
    event = meaningful_metric_change(database, snapshot)
    if event is not None:
        deliver_notification(database, event)


def notify_scheduled_report(database: Session, report: models.Report) -> None:
    if report.generation_reason != "scheduled":
        return
    deliver_notification(
        database,
        NotificationEvent(
            event_key=f"scheduled-report:report:{report.id}",
            client_id=report.client_id,
            category="scheduled_report_available",
            importance="medium",
            explanation=f'{report.title} is available for review.',
            requested_action="Review the report before sharing or taking its proposed next steps.",
            related_record_type="report",
            related_record_id=report.id,
        ),
    )


def notify_scheduled_job_failure(
    database: Session,
    job: models.ScheduledJob,
    error: str,
) -> None:
    """Notify a client when its recurring job fails; dedupe by failure episode."""
    if not job.client_id:
        return
    deliver_notification(
        database,
        NotificationEvent(
            event_key=f"scheduled-job-failure:{job.id}:{job.consecutive_failures}",
            client_id=job.client_id,
            category="scheduled_job_failure",
            importance="high" if job.consecutive_failures >= 2 else "medium",
            explanation=f"Scheduled {job.job_type} failed ({job.consecutive_failures} consecutive failure(s)): {error}"[:600],
            requested_action="Review the job error and restore the required connection or access before the next retry.",
            related_record_type="scheduled_job",
            related_record_id=job.id,
        ),
    )


def notify_ai_budget_threshold(
    database: Session,
    record: models.AIUsageRecord,
    budget_state: str,
) -> None:
    if not record.client_id:
        return
    now = record.created_at or datetime.utcnow()
    deliver_notification(
        database,
        NotificationEvent(
            event_key=f"ai-budget:{record.client_id}:{now.strftime('%Y-%m')}:{budget_state}",
            client_id=record.client_id,
            category="cost_threshold_exceeded",
            importance="high" if budget_state in {"strong_warning", "stop"} else "medium",
            explanation=f"AI usage reached the {budget_state.replace('_', ' ')} threshold for this month.",
            requested_action="Review AI usage, switch eligible work to the Codex handoff path, or increase the approved monthly budget.",
            related_record_type="ai_usage",
            related_record_id=record.id,
        ),
    )
