"""Deterministic, source-labeled report assembly for Phase 11."""

from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from html import escape
import re
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.metric_rules import calculate_change


SOURCE_LABELS = {
    "manual": "Manual data",
    "mock": "Mock data",
    "imported": "Imported data",
    "live_api": "Live API data",
}


def source_label(source_type: str) -> str:
    return SOURCE_LABELS.get(source_type, f"Other source: {source_type}")


def json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def metric_facts(database: Session, client_id: str, period_end: date) -> list[dict]:
    snapshots = list(
        database.scalars(
            select(models.MetricSnapshot)
            .where(
                models.MetricSnapshot.client_id == client_id,
                models.MetricSnapshot.measurement_period <= period_end.strftime("%Y-%m"),
            )
            .order_by(
                models.MetricSnapshot.metric_name,
                models.MetricSnapshot.measurement_period,
                models.MetricSnapshot.recorded_at,
                models.MetricSnapshot.id,
            )
        )
    )
    by_metric: dict[str, list] = defaultdict(list)
    for snapshot in snapshots:
        by_metric[snapshot.metric_name].append(snapshot)

    facts = []
    for metric_name, history in sorted(by_metric.items()):
        latest_by_period = {}
        for snapshot in history:
            latest_by_period[snapshot.measurement_period] = snapshot
        ordered = [latest_by_period[key] for key in sorted(latest_by_period)]
        baseline = next((item for item in history if item.is_baseline), None)
        previous = ordered[-2] if len(ordered) > 1 else None
        current = ordered[-1]
        previous_change = None
        baseline_change = None
        if previous is not None:
            previous_change = calculate_change(metric_name, current.value, previous.value)
        if baseline is not None and baseline.id != current.id:
            baseline_change = calculate_change(metric_name, current.value, baseline.value)
        facts.append(
            {
                "metric_name": metric_name,
                "baseline": metric_point(baseline),
                "previous": metric_point(previous),
                "current": metric_point(current),
                "change_from_previous": previous_change,
                "change_from_baseline": baseline_change,
            }
        )
    return facts


def metric_point(snapshot) -> Optional[dict]:
    if snapshot is None:
        return None
    return {
        "value": json_value(snapshot.value),
        "period": snapshot.measurement_period,
        "source_type": snapshot.source_type,
        "source_label": source_label(snapshot.source_type),
    }


def website_metric_facts(database: Session, client_id: str, period_end: date) -> list[dict]:
    snapshots = list(
        database.scalars(
            select(models.WebsiteMetricSnapshot)
            .where(
                models.WebsiteMetricSnapshot.client_id == client_id,
                models.WebsiteMetricSnapshot.period_end <= period_end,
                models.WebsiteMetricSnapshot.window_days == 30,
            )
            .order_by(models.WebsiteMetricSnapshot.period_end, models.WebsiteMetricSnapshot.id)
        )
    )
    if not snapshots:
        return []
    current = snapshots[-1]
    previous = snapshots[-2] if len(snapshots) > 1 else None
    fields = ["unique_visitors", "pageviews", "call_clicks", "form_submits"]
    results = []
    for field in fields:
        current_value = getattr(current, field)
        previous_value = getattr(previous, field) if previous else None
        results.append(
            {
                "metric_name": f"website_{field}",
                "baseline": None,
                "previous": website_point(previous, previous_value, period_end),
                "current": website_point(current, current_value, period_end),
                "change_from_previous": (
                    calculate_change("calls", current_value, previous_value)
                    if previous_value is not None
                    else None
                ),
                "change_from_baseline": None,
            }
        )
    return results


def website_point(snapshot, value, report_period_end: Optional[date] = None) -> Optional[dict]:
    if snapshot is None:
        return None
    stale_days = (
        max(0, (report_period_end - snapshot.period_end).days)
        if report_period_end is not None
        else 0
    )
    return {
        "value": value,
        "period": f"{snapshot.period_start.isoformat()} to {snapshot.period_end.isoformat()}",
        "source_type": "live_api",
        "source_label": source_label("live_api"),
        "source_detail": snapshot.source,
        "recorded_at": json_value(snapshot.recorded_at),
        "stale_days": stale_days,
        "freshness": "stale" if stale_days else "current",
    }


def verified_work(database: Session, client_id: str, start: datetime, end: datetime) -> list[dict]:
    decisions = list(
        database.scalars(
            select(models.ExecutionVerification)
            .where(
                models.ExecutionVerification.client_id == client_id,
                models.ExecutionVerification.outcome == "verified",
                models.ExecutionVerification.decided_at >= start,
                models.ExecutionVerification.decided_at < end,
            )
            .order_by(models.ExecutionVerification.decided_at, models.ExecutionVerification.id)
        )
    )
    work = []
    for decision in decisions:
        task = database.get(models.Task, decision.task_id)
        execution = database.get(models.FulfillmentExecution, decision.execution_id)
        if task is None or execution is None:
            continue
        if task.client_id != client_id or execution.client_id != client_id:
            continue
        work.append(
            {
                "task_id": task.id,
                "title": task.title,
                "requested_outcome": task.requested_outcome,
                "verification_id": decision.id,
                "verified_at": decision.decided_at.isoformat(),
                "reviewer": decision.reviewer,
                "changed_files": execution.simulated_changed_files,
            }
        )
    return work


def outcome_measurements(database: Session, client_id: str, start: datetime, end: datetime) -> list[dict]:
    """Return source-backed post-work measurements for the reporting window."""
    rows = list(
        database.scalars(
            select(models.OutcomeMeasurement)
            .where(
                models.OutcomeMeasurement.client_id == client_id,
                models.OutcomeMeasurement.observed_at >= start,
                models.OutcomeMeasurement.observed_at < end,
            )
            .order_by(models.OutcomeMeasurement.observed_at, models.OutcomeMeasurement.id)
        )
    )
    return [
        {
            "id": row.id,
            "task_id": row.task_id,
            "execution_id": row.execution_id,
            "metric_name": row.metric_name,
            "baseline_value": row.baseline_value,
            "observed_value": row.observed_value,
            "unit": row.unit,
            "assessment": row.assessment,
            "source_type": row.source_type,
            "source_reference": row.source_reference,
            "evidence": row.evidence,
            "notes": row.notes,
            "recorded_by": row.recorded_by,
            "observed_at": row.observed_at.isoformat(),
        }
        for row in rows
    ]


def build_evidence_provenance(snapshot: dict) -> list[dict]:
    """Build a compact, auditable index of the evidence behind a report."""
    rows: list[dict] = []
    for access in snapshot.get("access", []):
        rows.append(
            {
                "kind": "integration",
                "source": access.get("source_label") or access.get("integration"),
                "status": access.get("status", "unknown"),
                "source_type": access.get("source_type", "unknown"),
                "observed_at": access.get("last_checked_at"),
                "record_ids": [],
                "limitations": list(access.get("issues") or []),
            }
        )
    for finding in snapshot.get("findings", []):
        rows.append(
            {
                "kind": "finding",
                "source": finding.get("source") or "Finding audit",
                "status": finding.get("status", "unknown"),
                "source_type": "evidence_backed",
                "observed_at": finding.get("last_seen_at") or finding.get("discovered_at"),
                "record_ids": [finding["id"]] if finding.get("id") else [],
                "limitations": [],
            }
        )
    for metric in snapshot.get("metrics", []):
        current = metric.get("current") or {}
        rows.append(
            {
                "kind": "metric",
                "source": current.get("source_label") or current.get("source_type") or "Metric snapshot",
                "status": current.get("freshness") or "recorded",
                "source_type": current.get("source_type", "unknown"),
                "observed_at": current.get("recorded_at") or current.get("period"),
                "record_ids": [],
                "limitations": [],
            }
        )
    update = snapshot.get("client_update") or {}
    for source in update.get("sources") or []:
        rows.append(
            {
                "kind": "audit",
                "source": str(source),
                "status": "consulted",
                "source_type": "portfolio_audit",
                "observed_at": snapshot.get("period", {}).get("end"),
                "record_ids": [],
                "limitations": list(update.get("blockers") or []),
            }
        )
    return rows[:200]


def build_report_snapshot(
    database: Session,
    client: models.Client,
    report_type: str,
    period_start: date,
    period_end: date,
    update_mode: str = "saved",
) -> dict:
    start_dt = datetime.combine(period_start, time.min)
    end_dt = datetime.combine(period_end + timedelta(days=1), time.min)

    health = database.scalar(
        select(models.HealthCheck)
        .where(
            models.HealthCheck.client_id == client.id,
            models.HealthCheck.checked_at < end_dt,
        )
        .order_by(models.HealthCheck.checked_at.desc(), models.HealthCheck.id.desc())
    )
    integrations = list(
        database.scalars(
            select(models.IntegrationConnection)
            .where(models.IntegrationConnection.client_id == client.id)
            .order_by(models.IntegrationConnection.integration_name)
        )
    )
    findings = list(
        database.scalars(
            select(models.Finding)
            .where(models.Finding.client_id == client.id)
            .order_by(models.Finding.discovered_at, models.Finding.id)
        )
    )
    tasks = list(
        database.scalars(
            select(models.Task)
            .where(models.Task.client_id == client.id)
            .order_by(models.Task.proposed_at, models.Task.id)
        )
    )
    executions = list(
        database.scalars(
            select(models.FulfillmentExecution)
            .where(
                models.FulfillmentExecution.client_id == client.id,
                models.FulfillmentExecution.started_at >= start_dt,
                models.FulfillmentExecution.started_at < end_dt,
            )
            .order_by(models.FulfillmentExecution.started_at, models.FulfillmentExecution.id)
        )
    )
    verifications = list(
        database.scalars(
            select(models.ExecutionVerification)
            .where(
                models.ExecutionVerification.client_id == client.id,
                models.ExecutionVerification.decided_at >= start_dt,
                models.ExecutionVerification.decided_at < end_dt,
            )
            .order_by(models.ExecutionVerification.decided_at, models.ExecutionVerification.id)
        )
    )
    metrics = metric_facts(database, client.id, period_end) + website_metric_facts(
        database, client.id, period_end
    )
    open_findings = [item for item in findings if item.status != "resolved"]
    failures = [
        {"kind": "task", "title": item.title, "status": item.status, "detail": item.reason}
        for item in tasks
        if item.status in {"failed", "blocked"}
    ]
    failures += [
        {
            "kind": "execution",
            "title": database.get(models.Task, item.task_id).title,
            "status": item.status,
            "detail": item.error_message or "No error detail recorded",
        }
        for item in executions
        if item.status in {"failed", "blocked"}
    ]
    failures += [
        {
            "kind": "verification",
            "title": database.get(models.Task, item.task_id).title,
            "status": item.outcome,
            "detail": item.explanation,
        }
        for item in verifications
        if item.outcome == "verification_failed"
    ]
    elapsed_days = max(0, (period_end - client.service_start_date).days)
    access = [
        {
            "integration": item.integration_name,
            "status": item.connection_status,
            "source_type": item.data_source_type,
            "source_label": source_label(item.data_source_type),
            "issues": item.issues,
            "last_checked_at": json_value(item.last_checked_at),
        }
        for item in integrations
    ]
    snapshot = {
        "report_type": report_type,
        "client": {
            "id": client.id,
            "business_name": client.business_name,
            "service_start_date": client.service_start_date.isoformat(),
            "days_with_agency": elapsed_days,
        },
        "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
        "health": (
            {
                "status": health.overall_status,
                "summary": health.summary,
                "website_status": health.website_status,
                "checked_at": health.checked_at.isoformat(),
            }
            if health
            else None
        ),
        "access": access,
        "findings": [
            {
                "id": item.id,
                "title": item.title,
                "explanation": item.explanation,
                "evidence": item.evidence,
                "source": item.source,
                "severity": item.severity,
                "confidence": item.confidence,
                "recommended_action": item.recommended_action,
                "status": item.status,
                "discovered_at": item.discovered_at.isoformat(),
                "last_seen_at": item.last_seen_at.isoformat(),
            }
            for item in findings
        ],
        "open_findings": [item.id for item in open_findings],
        "tasks": [
            {
                "id": item.id,
                "title": item.title,
                "status": item.status,
                "risk": item.risk,
                "requested_outcome": item.requested_outcome,
            }
            for item in tasks
        ],
        "pending_approvals": [item.id for item in tasks if item.status == "proposed"],
        "failures_and_blockers": failures,
        "estimated_execution_cost": round(sum(item.estimated_cost for item in executions), 2),
        "cost_label": "Recorded execution cost",
        "metrics": metrics,
        "verified_work": verified_work(database, client.id, start_dt, end_dt),
        "outcome_measurements": outcome_measurements(database, client.id, start_dt, end_dt),
        "fulfillment_executions": [
            {
                "id": execution.id,
                "task_id": execution.task_id,
                "status": execution.status,
                "executor": execution.evidence.get("executor", "unknown"),
                "summary": execution.evidence.get("summary", ""),
                "deployment": execution.evidence.get("deployment"),
            }
            for execution in executions
        ],
        "healthy_no_action": bool(
            health and health.overall_status == "healthy" and not open_findings
        ),
    }
    if update_mode in {"simple", "in_depth"}:
        from app.client_update_service import generate_portfolio_update

        update = generate_portfolio_update(database, mode=update_mode, client=client).clients[0]
        update_data = asdict(update)
        if not any(update_data[key] for key in ("plan_30", "plan_60", "plan_90")):
            update_data["plan_30"] = [
                "Review the latest saved findings, approvals, and fulfillment queue, then convert the highest-priority item into an approved task."
            ]
        for horizon in ("plan_30", "plan_60", "plan_90"):
            update_data[horizon] = [
                {
                    "plan_item_id": f"{horizon}_{index}",
                    "action": action,
                    "expected_result": expected_result_for_action(action),
                    "success_metric": success_metric_for_action(action),
                    "verification_window": verification_window_for_horizon(horizon),
                }
                for index, action in enumerate(update_data[horizon])
            ]
        snapshot["client_update"] = update_data
        # In-depth audits materialize their gaps as durable findings. Reload
        # them so this very report contains the exact finding/task source of
        # the recommendations it just generated.
        refreshed_findings = list(
            database.scalars(
                select(models.Finding)
                .where(models.Finding.client_id == client.id)
                .order_by(models.Finding.discovered_at, models.Finding.id)
            )
        )
        snapshot["findings"] = [
            {
                "id": item.id,
                "title": item.title,
                "explanation": item.explanation,
                "evidence": item.evidence,
                "source": item.source,
                "severity": item.severity,
                "confidence": item.confidence,
                "recommended_action": item.recommended_action,
                "status": item.status,
                "discovered_at": item.discovered_at.isoformat(),
                "last_seen_at": item.last_seen_at.isoformat(),
            }
            for item in refreshed_findings
        ]
        snapshot["open_findings"] = [item.id for item in refreshed_findings if item.status != "resolved"]
    # Attach the source finding to every recommendation so an owner can trace
    # a proposed task back to the observation that caused it.
    finding_candidates = snapshot.get("findings", [])
    for horizon in ("plan_30", "plan_60", "plan_90"):
        for item in (snapshot.get("client_update") or {}).get(horizon, []):
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "").casefold().strip()
            match = next(
                (
                    finding
                    for finding in finding_candidates
                    if action
                    and (
                        str(finding.get("recommended_action") or "").casefold().strip() == action
                        or action in str(finding.get("recommended_action") or "").casefold()
                        or str(finding.get("title") or "").casefold() in action
                    )
                ),
                None,
            )
            item["evidence_provenance"] = (
                {
                    "finding_id": match.get("id"),
                    "source": match.get("source") or "Finding audit",
                    "observed_at": match.get("last_seen_at") or match.get("discovered_at"),
                    "status": match.get("status", "unknown"),
                }
                if match
                else {
                    "finding_id": None,
                    "source": "Portfolio audit",
                    "observed_at": snapshot.get("period", {}).get("end"),
                    "status": "audit_summary",
                }
            )
    snapshot["evidence_provenance"] = build_evidence_provenance(snapshot)
    snapshot["retention_risk"] = build_retention_risk(snapshot)
    snapshot["client_message"] = build_client_message(snapshot)
    return snapshot


def expected_result_for_action(action: str) -> str:
    """Give a measurable follow-up without promising rankings or leads."""
    text = action.casefold()
    if any(term in text for term in ("title", "description", "h1", "snippet")):
        return "Verify the page is live, then compare Search Console impressions and click-through rate in the next reporting cycle."
    if any(term in text for term in ("sitemap", "robots", "canonical", "index", "crawl")):
        return "Verify crawl/indexing signals and Search Console coverage after the change; no ranking improvement is guaranteed."
    if any(term in text for term in ("service page", "location", "content", "internal link")):
        return "Verify the page is live and indexed, then compare relevant impressions, clicks, calls, forms, or qualified leads over 30-90 days."
    if any(term in text for term in ("google business", "gbp", "profile")):
        return "Verify the live profile reflects approved facts and compare profile actions or calls after the next reporting period."
    if any(term in text for term in ("cta", "call", "form", "conversion")):
        return "Verify the conversion path works on mobile and compare recorded calls, forms, bookings, or qualified leads."
    return "Verify completion with source evidence, then compare the relevant traffic, visibility, or conversion metric in the next reporting cycle."


def success_metric_for_action(action: str) -> str:
    """Name the observable signal that determines whether an action helped."""
    text = action.casefold()
    if any(term in text for term in ("title", "description", "snippet")):
        return "Search Console impressions, clicks, and click-through rate for the affected pages"
    if any(term in text for term in ("sitemap", "robots", "canonical", "index", "crawl")):
        return "Successful crawl/indexing evidence and affected-page coverage in Search Console"
    if any(term in text for term in ("service page", "location", "content", "internal link")):
        return "Affected-page impressions, clicks, calls, forms, bookings, or qualified leads"
    if any(term in text for term in ("google business", "gbp", "profile", "hours", "category")):
        return "Verified profile fields plus profile actions, calls, or direction requests"
    if any(term in text for term in ("cta", "call", "form", "conversion", "booking")):
        return "Tracked calls, forms, bookings, or qualified leads from the changed path"
    return "The source-specific visibility, traffic, or conversion metric named in the verification evidence"


def verification_window_for_horizon(horizon: str) -> str:
    """Keep the plan time-bound without pretending SEO outcomes are guaranteed."""
    return {
        "today": "Resolve the blocker, then rerun the affected check before assigning execution work",
        "plan_30": "Verify implementation immediately; compare early signals over the next 30 days",
        "plan_60": "Verify implementation immediately; compare the affected metric over 31–60 days",
        "plan_90": "Verify implementation immediately; compare the affected metric over 61–90 days",
    }.get(horizon, "Verify implementation and compare the affected metric in the next reporting cycle")


def build_retention_risk(snapshot: dict) -> dict:
    """Summarize operational value risk from recorded evidence, not churn intent."""
    reasons: list[str] = []
    mitigations: list[str] = []
    if snapshot.get("failures_and_blockers"):
        reasons.append("Recorded failures or blockers may delay visible progress.")
        mitigations.append("Resolve the listed blocker and document the next verification point.")
    if snapshot.get("open_findings"):
        reasons.append("Open findings remain without a recorded resolution.")
        mitigations.append("Prioritize the highest-severity open finding and propose an approvable task.")
    if not snapshot.get("verified_work"):
        reasons.append("No independently verified work was recorded in this period.")
        mitigations.append("Complete one scoped task and attach source evidence for the next report.")
    if not snapshot.get("metrics"):
        reasons.append("No current metric history was available to demonstrate movement.")
        mitigations.append("Connect or refresh the relevant measurement source before the next cycle.")
    update = snapshot.get("client_update") or {}
    if update.get("blockers"):
        reasons.append("The update could not verify all requested inputs or outcomes.")
        mitigations.append("Collect the access or client information listed in the report.")
    level = "high" if len(reasons) >= 3 else "medium" if reasons else "low"
    return {
        "level": level,
        "label": "Operational value risk (not a prediction of client intent)",
        "reasons": reasons or ["Current evidence shows ongoing work and no recorded value-communication gap."],
        "mitigations": mitigations or ["Continue the approved plan and verify the next measurable result."],
    }


def build_client_message(snapshot: dict) -> str:
    """Create an approval-gated, evidence-only message suitable for a client channel."""
    client_name = snapshot["client"]["business_name"]
    verified = snapshot.get("verified_work") or []
    wins = ", ".join(item["title"] for item in verified[:3]) or "No work was independently verified in this period."
    metrics = []
    for item in (snapshot.get("metrics") or [])[:4]:
        current = item.get("current")
        if current:
            metrics.append(f"{item['metric_name'].replace('_', ' ').title()}: {current['value']} ({current['source_label']})")
    update = snapshot.get("client_update") or {}
    next_items = [item["action"] for item in update.get("plan_30", [])[:3] if isinstance(item, dict)]
    if not next_items:
        next_items = [item["recommended_action"] for item in snapshot.get("findings", []) if item["id"] in set(snapshot.get("open_findings", []))][:3]
    needs = update.get("needs") or []
    lines = [
        f"Hi {client_name},",
        "Here is your latest progress update.",
        f"Verified work: {wins}",
    ]
    if metrics:
        lines.append("Recorded metrics: " + "; ".join(metrics) + ".")
    lines.append("Next focus: " + ("; ".join(next_items) if next_items else "Continue monitoring and verify the next approved action."))
    if needs:
        lines.append("To continue, we need: " + "; ".join(needs[:3]) + ".")
    lines.append("We will report the next verified change and any limitations clearly in the next cycle.")
    return "\n".join(lines)


def source_badge(point: Optional[dict]) -> str:
    if point is None:
        return '<span class="report-source source-none">No data</span>'
    return f'<span class="report-source source-{escape(point["source_type"])}">{escape(point["source_label"])}</span>'


def result_cell(point: Optional[dict]) -> str:
    if point is None:
        return '<span class="report-missing">Not recorded</span>'
    return (
        f'<strong>{escape(str(point["value"]))}</strong>'
        f'<small>{escape(point["period"])}</small>{source_badge(point)}'
    )


def change_text(change: Optional[dict]) -> str:
    if change is None:
        return "Not enough history"
    amount = change["amount"]
    direction = "increased" if amount > 0 else "decreased" if amount < 0 else "did not change"
    percent = f' ({abs(change["percent"])}%)' if change.get("percent") is not None else ""
    return f"{direction} by {abs(amount)}{percent}"


def render_metrics(metrics: list[dict]) -> str:
    if not metrics:
        return '<p class="report-empty">No metric results were recorded.</p>'
    rows = []
    for item in metrics:
        rows.append(
            f'<div class="report-metric-row"><span>{escape(item["metric_name"].replace("_", " ").title())}</span>'
            f'<span>{result_cell(item["baseline"])}</span><span>{result_cell(item["previous"])}</span>'
            f'<span>{result_cell(item["current"])}</span><span>{escape(change_text(item["change_from_previous"]))}</span></div>'
        )
    return "".join(rows)


def render_evidence_provenance(provenance: list[dict], *, client_safe: bool = False) -> str:
    if not provenance:
        return '<section><h2>Evidence provenance</h2><p class="report-empty">No source trail was recorded.</p></section>'
    rows = []
    for item in provenance:
        source = escape(str(item.get("source") or "Unknown source"))
        status = escape(str(item.get("status") or "unknown").replace("_", " "))
        source_type = escape(str(item.get("source_type") or "unknown"))
        observed = escape(str(item.get("observed_at") or "date not recorded"))
        limitation = ""
        if item.get("limitations"):
            limitation = " · Limitation recorded" if client_safe else f" · {escape('; '.join(map(str, item['limitations'])))}"
        record_ids = ""
        if not client_safe and item.get("record_ids"):
            record_ids = f" · Records: {escape(', '.join(map(str, item['record_ids'])))}"
        rows.append(f"<li><strong>{source}</strong><span>{status} · {source_type}</span><small>Observed: {observed}{record_ids}{limitation}</small></li>")
    return f'<section><h2>Evidence provenance</h2><p>Every recommendation and result is tied to the source and observation date available when this report was generated.</p><ul class="report-list">{"".join(rows)}</ul></section>'


def render_update_plan(update: Optional[dict], *, heading: str = "Action plan and expected results") -> str:
    """Render the evidence-backed 30/60/90 plan for either report audience."""
    if not update:
        return ""
    plan_sections = []
    for label, key in (("Next 0-30 days", "plan_30"), ("Days 31-60", "plan_60"), ("Days 61-90", "plan_90")):
        items = "".join(
            f'<li><strong>{escape(item["action"])}</strong>'
            f'<span>Expected result: {escape(item["expected_result"])}</span>'
            f'<span>Success metric: {escape(item.get("success_metric", "Source evidence and the affected performance metric"))}</span>'
            f'<small>{escape(item.get("verification_window", "Verify in the next reporting cycle"))}'
            f'{" · Evidence source: " + escape(str((item.get("evidence_provenance") or {}).get("source") or "Portfolio audit"))}</small></li>'
            for item in update.get(key, [])
        ) or "<li>No additional action was generated for this horizon.</li>"
        plan_sections.append(f'<h3>{label}</h3><ol class="report-list">{items}</ol>')
    blockers = "".join(f"<li>{escape(item)}</li>" for item in update.get("blockers", [])) or "<li>None recorded.</li>"
    needs = "".join(f"<li>{escape(item)}</li>" for item in update.get("needs", [])) or "<li>No additional access requested.</li>"
    return f'''
      <section><h2>{escape(heading)}</h2>
        <p>These are evidence-backed actions. Expected results are what will be measured; rankings, traffic, and leads are not guaranteed.</p>
        {"".join(plan_sections)}
      </section>
      <section class="report-split"><div><h2>What could not be verified</h2><ul class="report-list">{blockers}</ul></div><div><h2>What is needed to continue</h2><ul class="report-list">{needs}</ul></div></section>
    '''


def render_retention_risk(risk: Optional[dict]) -> str:
    if not risk:
        return ""
    reasons = "".join(f"<li>{escape(item)}</li>" for item in risk.get("reasons", []))
    mitigations = "".join(f"<li>{escape(item)}</li>" for item in risk.get("mitigations", []))
    return f'''<section class="report-callout retention-risk"><h2>Retention-risk summary</h2>
      <p><strong>{escape(risk.get("level", "unknown").title())}</strong> — {escape(risk.get("label", "Evidence summary"))}</p>
      <div class="report-split"><div><h3>Evidence</h3><ul class="report-list">{reasons}</ul></div>
      <div><h3>Recommended mitigation</h3><ul class="report-list">{mitigations}</ul></div></div>
    </section>'''


def render_client_message(message: Optional[str]) -> str:
    if not message:
        return ""
    return f'''<section><h2>Draft client message</h2>
      <p>This message is a draft and requires owner approval before delivery.</p>
      <pre class="client-message">{escape(message)}</pre>
    </section>'''


def render_internal_report(snapshot: dict) -> str:
    health = snapshot["health"]
    health_html = (
        f'<strong>{escape(health["status"].replace("_", " ").title())}</strong><p>{escape(health["summary"])}</p>'
        if health
        else '<strong>Not enough data</strong><p>No health check was recorded.</p>'
    )
    access = "".join(
        f'<li><strong>{escape(item["integration"])}</strong> — {escape(item["status"])} {source_badge(item)}'
        f'<span>{escape("; ".join(item["issues"]) or "No access issue recorded")}</span></li>'
        for item in snapshot["access"]
    ) or '<li>No integrations recorded.</li>'
    findings = "".join(
        f'<article><span>{escape(item["severity"])} · {escape(item["status"])}</span><h3>{escape(item["title"])}</h3>'
        f'<p>{escape(item["explanation"])}</p><pre>{escape(str(item["evidence"]))}</pre><small>Source: {escape(item["source"])}</small></article>'
        for item in snapshot["findings"]
    ) or '<p class="report-empty">No findings recorded.</p>'
    tasks = "".join(
        f'<li><strong>{escape(item["title"])}</strong><span>{escape(item["status"])} · {escape(item["risk"])} risk</span></li>'
        for item in snapshot["tasks"]
    ) or '<li>No tasks recorded.</li>'
    failures = "".join(
        f'<li><strong>{escape(item["title"])}</strong><span>{escape(item["status"].replace("_", " "))}: {escape(item["detail"])}</span></li>'
        for item in snapshot["failures_and_blockers"]
    ) or '<li>No failures or blockers recorded.</li>'
    fulfillment = "".join(
        f'<li><strong>{escape(item["executor"])}</strong><span>{escape(item["status"])} · {escape(item["summary"])}</span>'
        f'<small>Deployment: {escape(str((item["deployment"] or {}).get("status", "not applicable")))}</small></li>'
        for item in snapshot.get("fulfillment_executions", [])
    ) or '<li>No fulfillment executions recorded.</li>'
    outcomes = "".join(
        f'<li><strong>{escape(item["metric_name"])}</strong><span>{escape(item["assessment"].replace("_", " "))} · '
        f'{escape(str(item["observed_value"]) if item["observed_value"] is not None else "value not numeric")} '
        f'{escape(item.get("unit") or "")}</span><small>Source: {escape(item["source_reference"])}</small></li>'
        for item in snapshot.get("outcome_measurements", [])
    ) or '<li>No post-fulfillment outcome measurements were recorded in this period.</li>'
    return f"""
      <section class="report-hero"><span>Internal operations report</span><h1>{escape(snapshot['client']['business_name'])}</h1><p>{escape(snapshot['period']['start'])} to {escape(snapshot['period']['end'])}</p></section>
      <section class="report-callout"><h2>Latest health</h2>{health_html}</section>
      <section><h2>Access and data sources</h2><ul class="report-list">{access}</ul></section>
      {render_evidence_provenance(snapshot.get("evidence_provenance", []))}
      <section><h2>Findings and evidence</h2><div class="report-findings">{findings}</div></section>
      <section><h2>Metric history</h2><div class="report-metric-head"><span>Metric</span><span>Baseline</span><span>Previous</span><span>Current</span><span>Change</span></div>{render_metrics(snapshot['metrics'])}</section>
      <section class="report-split"><div><h2>Task status and risks</h2><ul class="report-list">{tasks}</ul></div><div><h2>Failures and blockers</h2><ul class="report-list">{failures}</ul></div></section>
      <section><h2>Fulfillment execution evidence</h2><ul class="report-list">{fulfillment}</ul></section>
      <section><h2>Measured outcomes</h2><ul class="report-list">{outcomes}</ul><p class="report-empty">A completed task is not an outcome claim; this section only includes source-backed measurements recorded after the verification window.</p></section>
      {render_retention_risk(snapshot.get("retention_risk"))}
      {render_update_plan(snapshot.get("client_update"))}
      {render_client_message(snapshot.get("client_message"))}
      <section class="report-summary"><div><span>Cost</span><strong>${snapshot['estimated_execution_cost']:.2f}</strong><small>{escape(snapshot['cost_label'])}</small></div><div><span>Pending approvals</span><strong>{len(snapshot['pending_approvals'])}</strong><small>Proposed tasks only</small></div><div><span>Open findings</span><strong>{len(snapshot['open_findings'])}</strong><small>Not resolved</small></div></section>
    """


def render_client_report(snapshot: dict) -> str:
    verified = "".join(
        f'<li><strong>{escape(item["title"])}</strong><span>{escape(item["requested_outcome"])}</span><small>Verified {escape(item["verified_at"][:10])}</small></li>'
        for item in snapshot["verified_work"]
    ) or '<li>No work was independently verified during this reporting period.</li>'
    open_ids = set(snapshot["open_findings"])
    unresolved = [item for item in snapshot["findings"] if item["id"] in open_ids]
    unresolved_html = "".join(
        f'<li><strong>{escape(item["title"])}</strong><span>{escape(item["explanation"])}</span></li>'
        for item in unresolved
    ) or '<li>Monitoring found no unresolved issue requiring action.</li>'
    failures = "".join(
        f'<li><strong>{escape(item["title"])}</strong><span>{escape(item["status"].replace("_", " "))}: {escape(client_safe_failure_detail(item))}</span></li>'
        for item in snapshot["failures_and_blockers"]
    ) or '<li>No failure or blocker was recorded during this reporting period.</li>'
    outcomes = "".join(
        f'<li><strong>{escape(item["metric_name"])}</strong><span>{escape(item["assessment"].replace("_", " "))}'
        f'{(" · " + escape(str(item["observed_value"])) + " " + escape(item.get("unit") or "")) if item["observed_value"] is not None else ""}</span>'
        f'<small>Measured from {escape(item["source_reference"])}</small></li>'
        for item in snapshot.get("outcome_measurements", [])
    ) or '<li>No post-work outcome measurement is available for this period.</li>'
    next_steps = "".join(
        f'<li>{escape(item["recommended_action"])}</li>' for item in unresolved
    ) or '<li>Continue monitoring current performance and verified client information.</li>'
    update = snapshot.get("client_update")
    plan_html = ""
    if update:
        gbp = update.get("structured_evidence", {}).get("google_business_profile")
        gbp_html = ""
        if gbp:
            gbp_html = (
                "<section><h2>Live GBP evidence</h2><ul class=\"report-list\">"
                f"<li><strong>Location</strong><span>{escape(str(gbp.get('location_name') or gbp.get('location_id')))}</span></li>"
                f"<li><strong>Categories</strong><span>{escape(', '.join(gbp.get('categories') or []) or 'Not returned')}</span></li>"
                f"<li><strong>Regular hours</strong><span>{'Verified' if gbp.get('hours_present') else 'Not returned'}</span></li>"
                f"<li><strong>Reviews</strong><span>{escape(str(gbp.get('review_count') if gbp.get('review_count') is not None else 'Unknown'))}; average rating {escape(str(gbp.get('average_rating') if gbp.get('average_rating') is not None else 'unknown'))}</span></li>"
                "</ul></section>"
            )
        plan_html = render_update_plan(update) + gbp_html
    healthy = (
        '<aside class="client-healthy"><strong>Healthy — no action needed.</strong><span>Monitoring found no meaningful issue requiring new work.</span></aside>'
        if snapshot["healthy_no_action"]
        else ""
    )
    return f"""
      <section class="report-hero client-report-hero"><span>Client progress report</span><h1>{escape(snapshot['client']['business_name'])}</h1><p>{escape(snapshot['period']['start'])} to {escape(snapshot['period']['end'])}</p></section>
      <p class="client-appreciation">Thank you for continuing to work with us. We appreciate the progress we are making together and will keep both improvements and challenges clear.</p>
      <section class="report-summary"><div><span>Service started</span><strong>{escape(snapshot['client']['service_start_date'])}</strong><small>{snapshot['client']['days_with_agency']} days together as of this report</small></div><div><span>Verified work</span><strong>{len(snapshot['verified_work'])}</strong><small>Reviewed completions only</small></div><div><span>Open issues</span><strong>{len(snapshot['open_findings'])}</strong><small>Still being monitored</small></div></section>
      {healthy}
      <section><h2>Results and measurable changes</h2><div class="report-metric-head"><span>Metric</span><span>Starting baseline</span><span>Previous</span><span>Current</span><span>Change</span></div>{render_metrics(snapshot['metrics'])}</section>
      <section><h2>Verified completed work</h2><ul class="report-list">{verified}</ul></section>
      <section><h2>Measured outcomes</h2><ul class="report-list">{outcomes}</ul><p class="report-empty">Results are reported only when the relevant source evidence is available; SEO and lead outcomes are not guaranteed.</p></section>
      {render_evidence_provenance(snapshot.get("evidence_provenance", []), client_safe=True)}
      <section class="report-split"><div><h2>Unresolved issues</h2><ul class="report-list">{unresolved_html}</ul></div><div><h2>Failures and blockers</h2><ul class="report-list">{failures}</ul></div></section>
      <section><h2>Simple next steps</h2><ol class="report-list">{next_steps}</ol></section>
      {plan_html}
      {render_client_message(snapshot.get("client_message"))}
    """


def client_safe_failure_detail(item: dict) -> str:
    """Keep client reports actionable without exposing internal diagnostics."""
    detail = " ".join(str(item.get("detail") or "").split())
    if not detail:
        return "The planned work needs attention; Max is reviewing the saved evidence."
    # Provider exception strings and accidental diagnostic payloads belong in
    # the owner report/audit log, not in a shareable client document.
    if re.search(
        r"(?i)(api[_ -]?key|access[_ -]?token|authorization|password|secret|credential|traceback|stack trace|exception:|\.env|private key)",
        detail,
    ):
        return "The planned work did not complete; Max is reviewing the connection or execution evidence."
    return detail[:500]


def render_report(snapshot: dict) -> str:
    if snapshot["report_type"] == "internal":
        return render_internal_report(snapshot)
    return render_client_report(snapshot)
