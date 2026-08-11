"""Phase 11 immutable internal and client-facing HTML reports."""

from datetime import date, datetime
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.audit import record_event
from app.database import get_database
from app.notification_service import notify_scheduled_report
from app.pdf_report import render_pdf
from app.report_builder import build_report_snapshot, render_report
from app.report_share_service import validate_report_share
from app.agency_access_service import require_reporting_access
from app.routes.tasks import propose_task, require_active_client, require_client, task_response
from app.slack_service import SlackIntegrationError, deliver_approved_report
from app.subscription_service import require_fulfillment_entitlement


router = APIRouter(tags=["reports"])
REPORT_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "report.html"
REPORTS_PAGE_PATH = Path(__file__).parent.parent / "templates" / "reports.html"


def validate_period(client: models.Client, period_start: date, period_end: date) -> None:
    if period_end < period_start:
        raise HTTPException(status_code=422, detail="Report end date must be on or after start date")
    if period_end < client.service_start_date:
        raise HTTPException(status_code=422, detail="Report period ends before client service began")


def create_report_record(
    database: Session,
    client_id: str,
    request: schemas.ReportCreate,
) -> models.Report:
    client = require_client(database, client_id)
    require_fulfillment_entitlement(database, client_id)
    if client.archived_at is not None or client.status == "archived":
        raise HTTPException(status_code=409, detail="Archived clients cannot receive new reports")
    validate_period(client, request.period_start, request.period_end)
    snapshot = build_report_snapshot(
        database,
        client,
        request.report_type,
        request.period_start,
        request.period_end,
        request.update_mode,
    )
    audience = "Internal Operations" if request.report_type == "internal" else "Client Progress"
    report = models.Report(
        client_id=client.id,
        report_type=request.report_type,
        period_start=request.period_start,
        period_end=request.period_end,
        title=f"{audience} Report — {client.business_name}",
        snapshot_data=snapshot,
        html_content=render_report(snapshot),
        generated_by=request.generated_by,
        generation_reason=request.generation_reason,
    )
    database.add(report)
    database.flush()
    notify_scheduled_report(database, report)
    database.commit()
    database.refresh(report)
    return report


@router.post(
    "/clients/{client_id}/reports",
    response_model=schemas.ReportRead,
    status_code=status.HTTP_201_CREATED,
)
def create_report(
    client_id: str,
    request: schemas.ReportCreate,
    database: Session = Depends(get_database),
) -> models.Report:
    return create_report_record(database, client_id, request)


@router.get("/clients/{client_id}/reports", response_model=list[schemas.ReportRead])
def list_client_reports(
    client_id: str,
    database: Session = Depends(get_database),
) -> list[models.Report]:
    require_client(database, client_id)
    return list(
        database.scalars(
            select(models.Report)
            .where(models.Report.client_id == client_id)
            .order_by(models.Report.created_at.desc(), models.Report.id.desc())
        )
    )


@router.get("/reports/{report_id}", response_model=schemas.ReportRead)
def read_report(report_id: str, database: Session = Depends(get_database)) -> models.Report:
    report = database.get(models.Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.post(
    "/reports/{report_id}/plan-items/{horizon}/{item_index}/task",
    response_model=schemas.TaskRead,
    status_code=status.HTTP_201_CREATED,
)
def propose_report_plan_task(
    report_id: str,
    horizon: str,
    item_index: int,
    request: schemas.ReportPlanTaskCreate,
    database: Session = Depends(get_database),
) -> dict:
    """Turn one saved report action into a normal approval-gated task."""
    report = database.get(models.Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    client = require_active_client(database, report.client_id)
    if horizon not in {"plan_30", "plan_60", "plan_90"} or item_index < 0:
        raise HTTPException(status_code=422, detail="Invalid report plan item")
    update = (report.snapshot_data or {}).get("client_update") or {}
    items = update.get(horizon)
    if not isinstance(items, list) or item_index >= len(items):
        raise HTTPException(status_code=404, detail="Report plan item not found")
    item = items[item_index]
    if not isinstance(item, dict) or not str(item.get("action", "")).strip():
        raise HTTPException(status_code=409, detail="Report plan item has no actionable recommendation")
    plan_item_id = str(item.get("plan_item_id") or f"{horizon}_{item_index}")
    rule_key = f"report_plan:{report.id}:{plan_item_id}"
    finding = database.scalar(
        select(models.Finding).where(
            models.Finding.client_id == client.id,
            models.Finding.rule_key == rule_key,
        )
    )
    if finding is None:
        action = str(item["action"])[:1000]
        success_metric = str(item.get("success_metric") or "Source evidence and the affected performance metric")[:1000]
        finding = models.Finding(
            client_id=client.id,
            rule_key=rule_key,
            title=action[:200],
            explanation=f"Recommended in report {report.id} for the {horizon.replace('plan_', '')} horizon.",
            evidence={
                "source": "report_plan",
                "report_id": report.id,
                "report_type": report.report_type,
                "period": (report.snapshot_data or {}).get("period"),
                "plan_item_id": plan_item_id,
                "expected_result": item.get("expected_result"),
                "success_metric": success_metric,
                "verification_window": item.get("verification_window"),
                "evidence_provenance": item.get("evidence_provenance"),
            },
            source="report_plan",
            severity="high" if request.risk == "high" else "warning" if request.risk == "medium" else "info",
            confidence="evidence_backed",
            recommended_action=action,
            status="open",
        )
        database.add(finding)
        database.flush()
    existing_task = database.scalar(
        select(models.Task).where(
            models.Task.client_id == client.id,
            models.Task.source_finding_id == finding.id,
            models.Task.status.in_({"proposed", "approved", "ready", "running", "blocked", "failed", "completed"}),
        )
    )
    if existing_task is not None:
        return task_response(database, existing_task)
    proposal = schemas.TaskCreate(
        source_finding_id=finding.id,
        title=str(item.get("action") or "Report recommendation")[:200],
        requested_outcome=str(item.get("action") or "Complete the report recommendation")[:1200],
        reason=f"Proposed from report {report.id}; expected result: {str(item.get('expected_result') or 'Verify the affected metric in the next cycle.')[:900]}",
        expected_result=str(item.get("expected_result") or "Verify the affected metric in the next cycle.")[:1200],
        success_metric=str(item.get("success_metric") or "Source evidence and the affected performance metric")[:500],
        verification_window=str(item.get("verification_window") or "Verify in the next reporting cycle.")[:300],
        estimated_effort=request.estimated_effort,
        risk=request.risk,
        required_access=request.required_access,
    )
    return propose_task(client.id, proposal, database)


@router.get("/reports/{report_id}/html", response_class=HTMLResponse)
def read_report_html(
    report_id: str,
    database: Session = Depends(get_database),
    message: str = "",
    error: str = "",
) -> HTMLResponse:
    report = database.get(models.Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    client = require_client(database, report.client_id)
    page = REPORT_TEMPLATE_PATH.read_text(encoding="utf-8")
    page = page.replace("{{TITLE}}", escape(report.title))
    page = page.replace("{{BUSINESS_NAME}}", escape(client.business_name))
    page = page.replace("{{CLIENT_ID}}", escape(client.id))
    page = page.replace("{{REPORT_TYPE}}", escape(report.report_type.title()))
    page = page.replace("{{GENERATED_BY}}", escape(report.generated_by))
    page = page.replace("{{CREATED_AT}}", report.created_at.strftime("%b %d, %Y at %I:%M %p"))
    page = page.replace("{{REPORT_WORKFLOW}}", render_report_workflow(database, report, message, error))
    page = page.replace("{{REPORT_CONTENT}}", report.html_content)
    return HTMLResponse(page)


@router.get("/reports/{report_id}/download", response_class=Response)
def download_report_html(report_id: str, database: Session = Depends(get_database)) -> Response:
    """Download the immutable HTML report for printing or browser PDF export."""
    report = database.get(models.Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return Response(
        content=report.html_content,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{report.id}.html"'},
    )


@router.get("/reports/{report_id}/pdf", response_class=Response)
def download_report_pdf(
    report_id: str,
    database: Session = Depends(get_database),
    _reporting_identity: str = Depends(require_reporting_access),
) -> Response:
    """Download a client report only after explicit owner approval."""
    report = database.get(models.Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.report_type == "client" and report.status != "approved":
        raise HTTPException(status_code=409, detail="Client report approval is required before PDF delivery")
    return Response(
        content=render_pdf(report.title, report.html_content),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report.id}.pdf"'},
    )


@router.get("/reports/{report_id}/share/{token}/pdf", response_class=Response)
def download_shared_report_pdf(
    report_id: str,
    token: str,
    database: Session = Depends(get_database),
) -> Response:
    """Serve only the approved, unrevoked client PDF represented by a share token."""
    report = database.get(models.Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report share not found or expired")
    validate_report_share(report, token)
    return Response(
        content=render_pdf(report.title, report.html_content),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report.id}.pdf"'},
    )


@router.post("/reports/{report_id}/share/revoke")
def revoke_report_share(
    report_id: str,
    owner_email: str = Depends(require_reporting_access),
    database: Session = Depends(get_database),
) -> dict:
    """Revoke a client link without deleting the immutable report."""
    report = database.get(models.Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.client_share_issued_at is None:
        raise HTTPException(status_code=409, detail="Report has no client share")
    report.client_share_revoked_at = datetime.utcnow()
    record_event(
        database,
        "report_share_revoked",
        actor=owner_email,
        client_id=report.client_id,
        record_type="report",
        record_id=report.id,
    )
    database.commit()
    return {"report_id": report.id, "revoked": True}


@router.post("/reports/{report_id}/approval", response_model=schemas.ReportRead)
def approve_report(
    report_id: str,
    request: schemas.ReportApprovalCreate,
    database: Session = Depends(get_database),
) -> models.Report:
    report = database.get(models.Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status == "approved":
        raise HTTPException(status_code=409, detail="Report is already approved")
    report.status = "approved"
    report.approved_by = request.approved_by
    report.approved_at = datetime.utcnow()
    record_event(
        database,
        "report_approved",
        actor=request.approved_by,
        client_id=report.client_id,
        record_type="report",
        record_id=report.id,
        details={"report_type": report.report_type},
    )
    database.commit()
    database.refresh(report)
    return report


@router.post(
    "/reports/{report_id}/slack-delivery",
    response_model=schemas.ReportDeliveryRead,
)
def deliver_report_to_slack(
    report_id: str,
    database: Session = Depends(get_database),
) -> models.ReportDelivery:
    """Deliver an approved client report to its verified client Slack channel."""
    report = database.get(models.Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    delivery = deliver_report_record(database, report)
    database.commit()
    database.refresh(delivery)
    return delivery


def deliver_report_record(
    database: Session,
    report: models.Report,
) -> models.ReportDelivery:
    """Run one delivery attempt and append its result to the report audit trail."""
    require_fulfillment_entitlement(database, report.client_id)
    existing = database.scalar(
        select(models.ReportDelivery).where(models.ReportDelivery.report_id == report.id)
    )
    previous_attempts = existing.attempt_count if existing is not None else 0
    try:
        delivery = deliver_approved_report(database, report)
    except SlackIntegrationError as error:
        if error.code in {
            "client_report_required",
            "report_approval_required",
            "slack_channel_not_connected",
        }:
            raise HTTPException(status_code=409, detail=error.code) from error
        raise HTTPException(status_code=503 if error.retryable else 502, detail=error.code) from error
    if delivery.attempt_count > previous_attempts:
        record_event(
            database,
            "report_delivery_succeeded" if delivery.status == "delivered" else "report_delivery_failed",
            actor=report.approved_by or "system",
            client_id=report.client_id,
            record_type="report",
            record_id=report.id,
            details={
                "delivery_id": delivery.id,
                "channel_id": delivery.channel_id,
                "attempt": delivery.attempt_count,
                "error": delivery.last_error,
            },
        )
    return delivery


def render_report_workflow(
    database: Session,
    report: models.Report,
    message: str = "",
    error: str = "",
) -> str:
    """Render approval, delivery, and append-only history for one report."""
    delivery = database.scalar(
        select(models.ReportDelivery).where(models.ReportDelivery.report_id == report.id)
    )
    events = list(
        database.scalars(
            select(models.AuditEvent)
            .where(
                models.AuditEvent.record_type == "report",
                models.AuditEvent.record_id == report.id,
            )
            .order_by(models.AuditEvent.created_at.desc(), models.AuditEvent.id.desc())
        )
    )
    notice = ""
    if message:
        notice = f'<p class="report-workflow-notice success">{escape(message)}</p>'
    if error:
        notice = f'<p class="report-workflow-notice error">{escape(error)}</p>'

    if report.report_type != "client":
        action = "<p>Internal reports remain inside Max and cannot be delivered to a client channel.</p>"
    elif report.status != "approved":
        action = f"""
          <form method="post" action="/dashboard/reports/{escape(report.id)}/approval">
            <label>Approver name<input name="approved_by" required maxlength="200" autocomplete="name"></label>
            <button type="submit">Approve client report</button>
          </form>
        """
    elif delivery is None:
        action = f"""
          <p>Approved by {escape(report.approved_by or 'Agency owner')}. The saved snapshot is ready to send.</p>
          <form method="post" action="/dashboard/reports/{escape(report.id)}/slack-delivery">
            <button type="submit">Deliver to client Slack channel</button>
          </form>
        """
    elif delivery.status == "failed":
        action = f"""
          <p>Delivery attempt {delivery.attempt_count} failed: <code>{escape(delivery.last_error or 'unknown_error')}</code>.</p>
          <form method="post" action="/dashboard/reports/{escape(report.id)}/slack-delivery">
            <button type="submit">Retry Slack delivery</button>
          </form>
        """
    else:
        delivered_at = delivery.delivered_at.strftime("%b %d, %Y at %I:%M %p") if delivery.delivered_at else "Recorded"
        action = (
            f"<p>Delivered to <code>{escape(delivery.channel_id)}</code> on {delivered_at}. "
            f"Slack timestamp: <code>{escape(delivery.message_timestamp or 'not returned')}</code>.</p>"
        )

    event_labels = {
        "report_approved": "Approved",
        "report_delivery_succeeded": "Delivered",
        "report_delivery_failed": "Delivery failed",
    }
    history = "".join(
        f"<li><strong>{escape(event_labels.get(event.event_type, event.event_type.replace('_', ' ').title()))}</strong>"
        f"<span>{event.created_at.strftime('%b %d, %Y at %I:%M %p')} · {escape(event.actor)}</span></li>"
        for event in events
    ) or "<li><span>No approval or delivery events yet.</span></li>"
    download_action = (
        f'<a href="/reports/{escape(report.id)}/pdf">Download PDF</a>'
        if report.report_type == "internal" or report.status == "approved"
        else "<span>PDF unlocks after approval</span>"
    )
    return f"""
      <section class="report-workflow" aria-labelledby="report-workflow-title">
        <header><div><span>Owner workflow</span><h2 id="report-workflow-title">Approval and delivery</h2></div>
        {download_action}</header>
        {notice}<div class="report-workflow-action"><strong>Status: {escape(report.status.title())}</strong>{action}</div>
        <details><summary>Audit history ({len(events)})</summary><ol>{history}</ol></details>
      </section>
    """


@router.post("/dashboard/reports/{report_id}/approval", response_class=RedirectResponse)
async def dashboard_approve_report(
    report_id: str,
    request: Request,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    encoded = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    approved_by = encoded.get("approved_by", [""])[-1]
    try:
        approval = schemas.ReportApprovalCreate(approved_by=approved_by)
        approve_report(report_id, approval, database)
    except (HTTPException, ValidationError) as exc:
        database.rollback()
        detail = getattr(exc, "detail", str(exc))
        return RedirectResponse(
            url=f"/reports/{report_id}/html?error={quote(str(detail))}", status_code=303
        )
    return RedirectResponse(
        url=f"/reports/{report_id}/html?message={quote('Report approved')}", status_code=303
    )


@router.post("/dashboard/reports/{report_id}/slack-delivery", response_class=RedirectResponse)
def dashboard_deliver_report(
    report_id: str,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    report = database.get(models.Report, report_id)
    if report is None:
        return RedirectResponse(url="/dashboard?error=Report%20not%20found", status_code=303)
    try:
        delivery = deliver_report_record(database, report)
        database.commit()
    except HTTPException as exc:
        database.rollback()
        return RedirectResponse(
            url=f"/reports/{report_id}/html?error={quote(str(exc.detail))}", status_code=303
        )
    message = "Report delivered" if delivery.status == "delivered" else "Delivery failed; retry is available"
    return RedirectResponse(
        url=f"/reports/{report_id}/html?message={quote(message)}", status_code=303
    )


def render_report_link(report: models.Report) -> str:
    return f"""
      <article class="saved-report-row">
        <div><span>{escape(report.report_type.title())}</span><h3>{escape(report.title)}</h3><small>{report.period_start.isoformat()} to {report.period_end.isoformat()} · generated by {escape(report.generated_by)}</small></div>
        <a href="/reports/{escape(report.id)}/html">Open HTML report</a>
      </article>
    """


@router.get("/dashboard/clients/{client_id}/reports", response_class=HTMLResponse)
def reports_page(
    client_id: str,
    database: Session = Depends(get_database),
    message: str = "",
    error: str = "",
) -> HTMLResponse:
    client = require_client(database, client_id)
    reports = list_client_reports(client_id, database)
    rows = "".join(render_report_link(report) for report in reports)
    if not rows:
        rows = '<p class="report-empty">No reports have been generated for this client.</p>'
    notice = f'<p class="form-notice success-notice">{escape(message)}</p>' if message else ""
    if error:
        notice = f'<p class="form-notice error-notice">{escape(error)}</p>'
    today = date.today()
    default_start = today.replace(day=1)
    page = REPORTS_PAGE_PATH.read_text(encoding="utf-8")
    page = page.replace("{{BUSINESS_NAME}}", escape(client.business_name))
    page = page.replace("{{CLIENT_ID}}", escape(client.id))
    page = page.replace("{{DEFAULT_START}}", default_start.isoformat())
    page = page.replace("{{DEFAULT_END}}", today.isoformat())
    page = page.replace("{{REPORTS}}", rows).replace("{{NOTICE}}", notice)
    return HTMLResponse(page)


@router.post("/dashboard/clients/{client_id}/reports", response_class=RedirectResponse)
async def reports_page_create(
    client_id: str,
    request: Request,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    encoded = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    values = {key: entries[-1] for key, entries in encoded.items()}
    try:
        report_request = schemas.ReportCreate(
            report_type=values.get("report_type", ""),
            period_start=values.get("period_start", ""),
            period_end=values.get("period_end", ""),
            generated_by=values.get("generated_by", ""),
            generation_reason="manual",
            update_mode=values.get("update_mode", "saved"),
        )
        report = create_report_record(database, client_id, report_request)
    except (HTTPException, ValidationError) as exc:
        database.rollback()
        detail = getattr(exc, "detail", str(exc))
        return RedirectResponse(
            url=f"/dashboard/clients/{client_id}/reports?error={quote(str(detail))}",
            status_code=303,
        )
    return RedirectResponse(url=f"/reports/{report.id}/html", status_code=303)
