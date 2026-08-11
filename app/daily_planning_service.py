"""Turn verified client state into deduplicated daily work priorities."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.client_update_service import ClientUpdate, generate_portfolio_update
from app.notification_service import notify_task_approval
from app.report_builder import (
    expected_result_for_action,
    success_metric_for_action,
    verification_window_for_horizon,
)
from app.subscription_service import require_fulfillment_entitlement


MAX_ITEMS_PER_CLIENT = 12


class DailyPlanTaskError(ValueError):
    """A plan item cannot safely become a task."""
FOCUS_TERMS = {
    "seo": {"seo", "search", "organic", "ranking", "website", "traffic", "lead", "page", "content", "sitemap", "schema", "google", "gbp", "title", "description", "link"},
    "fulfillment": set(),
    "reporting": {"report", "metric", "analytics", "search console", "performance"},
    "all": set(),
}


def _matches_focus(text: str, focus: str) -> bool:
    terms = FOCUS_TERMS.get(focus, set())
    return not terms or any(term in text.casefold() for term in terms)


def _task_items(database: Session, client_id: str, focus: str) -> list[dict[str, Any]]:
    tasks = list(
        database.scalars(
            select(models.Task)
            .where(
                models.Task.client_id == client_id,
                models.Task.status.in_({"proposed", "approved", "ready", "blocked", "failed", "completed", "verified"}),
            )
            .order_by(models.Task.proposed_at.asc(), models.Task.id.asc())
        )
    )
    items = []
    for task in tasks:
        combined = f"{task.title} {task.requested_outcome}"
        if focus != "fulfillment" and not _matches_focus(combined, focus):
            continue
        if task.status in {"approved", "ready"}:
            bucket = "ready_now"
            next_step = "Begin the approved work, capture execution evidence, and leave verification separate."
        elif task.status == "proposed":
            bucket = "needs_approval"
            next_step = f"Review and approve or reject task `{task.id}` in this Slack conversation."
        elif task.status == "completed":
            bucket = "needs_verification"
            next_step = "Review the saved execution evidence and verify the outcome before calling it done."
        elif task.status == "verified":
            latest_measurement = database.scalar(
                select(models.OutcomeMeasurement)
                .where(
                    models.OutcomeMeasurement.client_id == client_id,
                    models.OutcomeMeasurement.task_id == task.id,
                )
                .order_by(models.OutcomeMeasurement.observed_at.desc(), models.OutcomeMeasurement.id.desc())
            )
            if latest_measurement is None or latest_measurement.assessment == "inconclusive":
                bucket = "needs_outcome_measurement"
                next_step = (
                    "Collect the source-specific result after the verification window and record it with "
                    f"`record outcome for task {task.id} {{JSON}}`; do not infer improvement from completion."
                )
            else:
                # A task with a measured result remains visible as context, but
                # does not compete with work that still needs action.
                continue
        else:
            bucket = "blocked"
            next_step = "Resolve the saved blocker/failure reason, then retry the existing task instead of creating a duplicate."
        items.append(
            {
                "title": task.title,
                "action": task.requested_outcome,
                "why": task.reason,
                "bucket": bucket,
                "horizon": "today",
                "effort": task.estimated_effort,
                "risk": task.risk,
                "required_access": task.required_access,
                "source": f"task:{task.id}",
                "task_id": task.id,
                "next_step": next_step,
                "expected_result": expected_result_for_action(task.requested_outcome),
                "success_metric": success_metric_for_action(task.requested_outcome),
                "verification_window": verification_window_for_horizon("today"),
            }
        )
    bucket_order = {
        "ready_now": 0,
        "needs_verification": 1,
        "needs_outcome_measurement": 2,
        "needs_approval": 3,
        "blocked": 4,
    }
    items.sort(key=lambda item: bucket_order[item["bucket"]])
    return items


def _recommendation_items(update: ClientUpdate, focus: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    horizons = (
        ("0-30_days", update.plan_30),
        ("31-60_days", update.plan_60),
        ("61-90_days", update.plan_90),
    )
    for horizon, actions in horizons:
        verification_horizon = {
            "0-30_days": "plan_30",
            "31-60_days": "plan_60",
            "61-90_days": "plan_90",
        }.get(horizon, horizon)
        for action in actions:
            if not _matches_focus(action, focus):
                continue
            items.append(
                {
                    "title": action[:200],
                    "action": action,
                    "why": "Recommended from the latest evidence-backed client audit.",
                    "bucket": "recommended",
                    "horizon": horizon,
                    "effort": "Needs scoping",
                    "risk": "medium",
                    "required_access": [],
                    "source": "fresh_audit_recommendation",
                    "next_step": "Confirm scope, convert this recommendation into one task, then execute through the normal evidence and verification workflow.",
                    "expected_result": expected_result_for_action(action),
                    "success_metric": success_metric_for_action(action),
                    "verification_window": verification_window_for_horizon(verification_horizon),
                }
            )
    for index, blocker in enumerate(update.blockers):
        need = update.needs[index] if index < len(update.needs) else "Provide the missing access or correct the saved connection."
        if not _matches_focus(f"{blocker} {need}", focus):
            continue
        items.append(
            {
                "title": blocker[:200],
                "action": need,
                "why": blocker,
                "bucket": "blocked",
                "horizon": "today",
                "effort": "Access/configuration",
                "risk": "low",
                "required_access": [need],
                "source": "fresh_audit_blocker",
                "next_step": need,
                "expected_result": "The saved access or provider blocker is resolved and the affected evidence can be collected.",
                "success_metric": "Successful provider or website evidence refresh for this client",
                "verification_window": verification_window_for_horizon("today"),
            }
        )
    return items


def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    seen: set[str] = set()
    for item in items:
        key = " ".join(item["action"].casefold().split())
        if key in seen:
            continue
        seen.add(key)
        results.append(item)
        if len(results) >= MAX_ITEMS_PER_CLIENT:
            break
    return results


def generate_daily_plans(
    database: Session,
    *,
    depth: str,
    focus: str,
    created_by: str,
    client: models.Client | None = None,
    plan_date: date | None = None,
    create_tasks: bool = False,
) -> list[models.DailyClientPlan]:
    if depth not in {"simple", "in_depth"}:
        raise ValueError("daily_plan_depth_invalid")
    if focus not in FOCUS_TERMS:
        raise ValueError("daily_plan_focus_invalid")
    if client is not None:
        require_fulfillment_entitlement(database, client.id)
    else:
        active_clients = list(
            database.scalars(select(models.Client).where(models.Client.archived_at.is_(None)))
        )
        for active_client in active_clients:
            require_fulfillment_entitlement(database, active_client.id)
    report = generate_portfolio_update(database, mode=depth, client=client)
    today = plan_date or date.today()
    saved_plans = []
    for update in report.clients:
        task_items = _task_items(database, update.client_id, focus)
        recommendation_items = _recommendation_items(update, focus) if depth == "in_depth" else []
        items = _deduplicate(task_items + recommendation_items)
        if not items:
            items = [
                {
                    "title": "Run a fresh in-depth client audit",
                    "action": "Run an in-depth daily plan to refresh website, Search Console, analytics, and access blockers before assigning work.",
                    "why": "No active evidence-backed tasks are currently available in this focus.",
                    "bucket": "recommended",
                    "horizon": "today",
                    "effort": "5–15 minutes plus integration response time",
                    "risk": "low",
                    "required_access": [],
                    "source": "planning_fallback",
                    "next_step": "Ask `in-depth daily plan for this client` in the mapped Slack channel.",
                }
            ]
        plan = database.scalar(
            select(models.DailyClientPlan).where(
                models.DailyClientPlan.client_id == update.client_id,
                models.DailyClientPlan.plan_date == today,
            )
        )
        source_summary = {
            "mode": update.mode,
            "verified_fact_count": len(update.facts),
            "gap_count": len(update.gaps),
            "blocker_count": len(update.blockers),
            "sources": update.sources,
            "finding_ids": list(update.persisted_finding_ids),
            "structured_evidence": update.structured_evidence,
            "refreshed_at": datetime.utcnow().isoformat(),
        }
        if plan is None:
            plan = models.DailyClientPlan(
                client_id=update.client_id,
                plan_date=today,
                depth=depth,
                focus=focus,
                items=items,
                source_summary=source_summary,
                created_by=created_by,
            )
            database.add(plan)
        else:
            plan.depth = depth
            plan.focus = focus
            plan.items = items
            plan.source_summary = source_summary
            plan.created_by = created_by
            plan.updated_at = datetime.utcnow()
        database.flush()
        if create_tasks:
            for item_index, item in enumerate(list(plan.items)):
                if item.get("bucket") not in {"recommended", "blocked"} or item.get("task_id"):
                    continue
                try:
                    convert_plan_item_to_task(
                        database,
                        plan,
                        item_index,
                        created_by=created_by,
                    )
                except DailyPlanTaskError:
                    # A malformed recommendation remains visible in the plan;
                    # it must never prevent other safe proposals from saving.
                    continue
        saved_plans.append(plan)
    return saved_plans


def render_slack_daily_plans(database: Session, plans: list[models.DailyClientPlan]) -> str:
    lines = [f"*Daily client plan · {len(plans)} client{'s' if len(plans) != 1 else ''}*"]
    labels = {
        "ready_now": "Can do now",
        "needs_verification": "Verify today",
        "needs_outcome_measurement": "Measure results",
        "needs_approval": "Needs approval",
        "blocked": "Blocked / access needed",
        "recommended": "Recommended next",
    }
    for plan in plans:
        client = database.get(models.Client, plan.client_id)
        lines.append(
            f"\n*{client.business_name if client else plan.client_id}* · `{plan.focus}` · `{plan.depth}` · `{plan.id}`"
        )
        for bucket in ("ready_now", "needs_verification", "needs_outcome_measurement", "needs_approval", "blocked", "recommended"):
            items = [(index, item) for index, item in enumerate(plan.items) if item["bucket"] == bucket]
            if not items:
                continue
            lines.append(f"*{labels[bucket]}:*")
            for index, item in items:
                source = f" · `{item['source']}`" if item.get("source", "").startswith("task:") else ""
                lines.append(
                    f"• *Item {index + 1}: {item['title']}* [{item['horizon']}]{source}\n"
                    f"  {item['next_step']}\n"
                    f"  Expected result: {item.get('expected_result', 'Verify the requested outcome with source evidence.')}\n"
                    f"  Success metric: {item.get('success_metric', 'The source-specific metric named in the evidence.')}\n"
                    f"  Verification: {item.get('verification_window', 'Verify in the next reporting cycle.')}"
                )
    return "\n".join(lines)[:35_000]


def convert_plan_item_to_task(
    database: Session,
    plan: models.DailyClientPlan,
    item_index: int,
    *,
    created_by: str,
) -> tuple[models.Task, bool]:
    """Convert one recommendation into an approval-required task exactly once."""
    if item_index < 0 or item_index >= len(plan.items):
        raise DailyPlanTaskError("daily_plan_item_not_found")
    # Copy JSON dictionaries before mutating so SQLAlchemy detects the plan update.
    updated_items = [dict(value) for value in plan.items]
    item = updated_items[item_index]
    existing_id = item.get("task_id") if isinstance(item, dict) else None
    if existing_id:
        existing = database.get(models.Task, existing_id)
        if existing is not None and existing.client_id == plan.client_id:
            return existing, True
    if not isinstance(item, dict) or not str(item.get("action", "")).strip():
        raise DailyPlanTaskError("daily_plan_item_has_no_action")
    rule_key = f"daily_plan:{plan.id}:{item_index}"
    finding = database.scalar(
        select(models.Finding).where(
            models.Finding.client_id == plan.client_id,
            models.Finding.rule_key == rule_key,
        )
    )
    if finding is not None:
        existing = database.scalar(
            select(models.Task).where(
                models.Task.client_id == plan.client_id,
                models.Task.source_finding_id == finding.id,
                models.Task.status.in_({"proposed", "approved", "ready", "running", "blocked", "failed", "completed"}),
            )
        )
        if existing is not None:
            item["task_id"] = existing.id
            plan.items = updated_items
            database.flush()
            return existing, True
    action = str(item.get("action", ""))[:1000]
    title = str(item.get("title") or action)[:200]
    reason = str(item.get("why") or "Recommended from the saved evidence-backed daily plan.")
    expected_result = str(item.get("expected_result") or "Verify the requested outcome with source evidence.")
    success_metric = str(item.get("success_metric") or "The source-specific metric named in the evidence.")
    verification_window = str(item.get("verification_window") or "Verify in the next reporting cycle.")
    reason = (
        f"{reason} Expected result: {expected_result} Success metric: {success_metric} "
        f"Verification window: {verification_window}"
    )[:1200]
    risk = str(item.get("risk") or "medium").casefold()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"
    finding = models.Finding(
        client_id=plan.client_id,
        rule_key=rule_key,
        title=title,
        explanation=reason,
        evidence={
            "source": "daily_client_plan",
            "plan_id": plan.id,
            "plan_date": plan.plan_date.isoformat(),
            "item_index": item_index,
            "item": item,
            "source_summary": plan.source_summary,
        },
        source="daily_plan",
        severity="high" if risk == "high" else "warning" if risk == "medium" else "info",
        confidence="evidence_backed",
        recommended_action=action,
        status="open",
    )
    database.add(finding)
    database.flush()
    task = models.Task(
        client_id=plan.client_id,
        source_finding_id=finding.id,
        title=title,
        requested_outcome=action[:1200],
        reason=reason,
        expected_result=expected_result[:1200],
        success_metric=success_metric[:500],
        verification_window=verification_window[:300],
        estimated_effort=str(item.get("effort") or "Needs scoping")[:120],
        risk=risk,
        required_access=[str(value)[:300] for value in (item.get("required_access") or [])][:20],
        status="proposed",
    )
    database.add(task)
    database.flush()
    database.add(
        models.TaskStatusEvent(
            client_id=task.client_id,
            task_id=task.id,
            from_status=None,
            to_status="proposed",
            changed_by=created_by,
            reason=f"Converted from daily plan {plan.id}, item {item_index}",
        )
    )
    notify_task_approval(database, task)
    item["task_id"] = task.id
    item["converted_by"] = created_by
    item["converted_at"] = datetime.utcnow().isoformat()
    plan.items = updated_items
    plan.updated_at = datetime.utcnow()
    database.flush()
    return task, False
