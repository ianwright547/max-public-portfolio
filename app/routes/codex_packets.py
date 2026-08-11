"""Safe, persistent Codex work-packet and human handoff endpoints."""

from html import escape
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.audit import record_event
from app.codex_packet_service import (
    WorkPacketError,
    create_work_packet,
    mark_packet_handed_off,
    prepare_connected_work_packet,
    packet_quality,
    record_codex_result,
    render_handoff_text,
)
from app.database import get_database
from app.notification_service import notify_task_approval
from app.routes.fulfillment import execution_response
from app.routes.tasks import require_active_client
from app.subscription_service import require_fulfillment_entitlement

router = APIRouter(tags=["codex work packets"])
HANDOFF_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "codex_handoff.html"
CONTENT_REVIEW_CHECKS = (
    "facts_supported",
    "intent_match",
    "human_writing_pass",
    "no_doorway_or_unsupported_claims",
    "links_and_cta_checked",
)


def packet_response(packet: models.CodexWorkPacket, reused_existing: bool = False) -> dict:
    return {
        "id": packet.id,
        "operation_key": packet.operation_key,
        "client_id": packet.client_id,
        "task_id": packet.task_id,
        "status": packet.status,
        "mode": packet.mode,
        "repository_owner": packet.repository_owner,
        "repository_name": packet.repository_name,
        "repository_url": packet.repository_url,
        "branch": packet.branch,
        "vercel_project_id": packet.vercel_project_id,
        "domain": packet.domain,
        "allowed_paths": packet.allowed_paths,
        "prohibited_paths": packet.prohibited_paths,
        "publishing_allowed": packet.publishing_allowed,
        "packet_data": packet.packet_data,
        "created_by": packet.created_by,
        "created_at": packet.created_at,
        "expires_at": packet.expires_at,
        "handed_off_by": packet.handed_off_by,
        "handed_off_at": packet.handed_off_at,
        "result_execution_id": packet.result_execution_id,
        "quality": packet_quality(packet),
        "reused_existing": reused_existing,
    }


def _content_review_response(review: models.ContentReview) -> dict:
    return {
        "id": review.id,
        "client_id": review.client_id,
        "task_id": review.task_id,
        "packet_id": review.packet_id,
        "execution_id": review.execution_id,
        "status": review.status,
        "reviewer": review.reviewer,
        "checklist": review.checklist,
        "notes": review.notes,
        "decided_at": review.decided_at,
        "created_at": review.created_at,
    }


@router.post(
    "/tasks/{task_id}/codex-work-packet",
    response_model=schemas.CodexWorkPacketRead,
    status_code=status.HTTP_201_CREATED,
)
def generate_work_packet(
    task_id: str,
    request: schemas.CodexWorkPacketCreate,
    database: Session = Depends(get_database),
) -> dict:
    task = database.get(models.Task, task_id)
    if task is not None:
        require_active_client(database, task.client_id)
        require_fulfillment_entitlement(database, task.client_id)
    try:
        packet, reused_existing = create_work_packet(database, task_id, request)
    except WorkPacketError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    return packet_response(packet, reused_existing)


@router.post(
    "/tasks/{task_id}/connected-codex-work-packet",
    response_model=schemas.CodexWorkPacketRead,
    status_code=status.HTTP_201_CREATED,
)
def generate_connected_work_packet(
    task_id: str,
    request: schemas.ConnectedCodexPacketCreate,
    database: Session = Depends(get_database),
) -> dict:
    """Build a packet from verified connections without repeating repository IDs."""
    task = database.get(models.Task, task_id)
    if task is not None:
        require_active_client(database, task.client_id)
        require_fulfillment_entitlement(database, task.client_id)
    try:
        packet, reused_existing = prepare_connected_work_packet(database, task_id, request)
    except WorkPacketError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    return packet_response(packet, reused_existing)


@router.get("/codex-work-packets/{packet_id}", response_model=schemas.CodexWorkPacketRead)
def read_work_packet(packet_id: str, database: Session = Depends(get_database)) -> dict:
    packet = database.get(models.CodexWorkPacket, packet_id)
    if packet is None:
        raise HTTPException(status_code=404, detail="Codex work packet not found")
    return packet_response(packet)


def require_packet(database: Session, packet_id: str) -> models.CodexWorkPacket:
    packet = database.get(models.CodexWorkPacket, packet_id)
    if packet is None:
        raise HTTPException(status_code=404, detail="Codex work packet not found")
    return packet


def _require_content_packet(packet: models.CodexWorkPacket) -> None:
    work_type = str((packet.packet_data or {}).get("local_seo_work_type", ""))
    if work_type not in {"local_page", "blog"}:
        raise HTTPException(status_code=409, detail="Content review applies only to local-page or blog packets")


@router.get("/codex-work-packets/{packet_id}/content-review", response_model=schemas.ContentReviewRead)
def read_content_review(packet_id: str, database: Session = Depends(get_database)) -> dict:
    packet = require_packet(database, packet_id)
    _require_content_packet(packet)
    review = database.scalar(
        select(models.ContentReview).where(models.ContentReview.packet_id == packet.id)
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Content review has not been recorded")
    return _content_review_response(review)


@router.post(
    "/codex-work-packets/{packet_id}/content-review",
    response_model=schemas.ContentReviewRead,
)
def record_content_review(
    packet_id: str,
    request: schemas.ContentReviewCreate,
    database: Session = Depends(get_database),
) -> dict:
    packet = require_packet(database, packet_id)
    _require_content_packet(packet)
    if packet.result_execution_id is None:
        raise HTTPException(status_code=409, detail="Record the completed Codex result before content review")
    execution = database.get(models.FulfillmentExecution, packet.result_execution_id)
    if execution is None or execution.status != "completed" or execution.client_id != packet.client_id:
        raise HTTPException(status_code=409, detail="Content review requires a completed result for this packet")
    missing = [key for key in CONTENT_REVIEW_CHECKS if key not in request.checklist]
    if missing:
        raise HTTPException(status_code=422, detail="Content review checklist is missing: " + ", ".join(missing))
    if any(not isinstance(request.checklist[key], bool) for key in CONTENT_REVIEW_CHECKS):
        raise HTTPException(status_code=422, detail="Content review checklist values must be boolean")
    if request.status == "approved" and not all(request.checklist[key] for key in CONTENT_REVIEW_CHECKS):
        failed = ", ".join(key for key in CONTENT_REVIEW_CHECKS if not request.checklist[key])
        raise HTTPException(status_code=409, detail="Content cannot be approved; failed checks: " + failed)
    review = database.scalar(select(models.ContentReview).where(models.ContentReview.packet_id == packet.id))
    now = datetime.utcnow()
    if review is None:
        review = models.ContentReview(
            client_id=packet.client_id,
            task_id=packet.task_id,
            packet_id=packet.id,
            execution_id=execution.id,
            status=request.status,
            reviewer=request.reviewer,
            checklist=request.checklist,
            notes=request.notes,
            decided_at=now,
        )
        database.add(review)
    else:
        review.status = request.status
        review.reviewer = request.reviewer
        review.checklist = request.checklist
        review.notes = request.notes
        review.execution_id = execution.id
        review.decided_at = now
    record_event(
        database,
        "content_review_recorded",
        actor=request.reviewer,
        client_id=packet.client_id,
        record_type="content_review",
        record_id=review.id,
        details={"packet_id": packet.id, "task_id": packet.task_id, "status": request.status},
    )
    database.commit()
    database.refresh(review)
    return _content_review_response(review)


@router.get("/codex-work-packets/{packet_id}/quality")
def read_work_packet_quality(packet_id: str, database: Session = Depends(get_database)) -> dict:
    """Return deterministic handoff-quality checks before anyone copies the packet."""
    return packet_quality(require_packet(database, packet_id))


@router.get("/codex-work-packets/{packet_id}/handoff", response_model=schemas.CodexHandoffRead)
def preview_codex_handoff(packet_id: str, database: Session = Depends(get_database)) -> dict:
    packet = require_packet(database, packet_id)
    return {"packet": packet_response(packet), "handoff_text": render_handoff_text(packet)}


@router.post("/codex-work-packets/{packet_id}/handoff", response_model=schemas.CodexHandoffRead)
def record_codex_handoff(
    packet_id: str,
    request: schemas.CodexHandoffCreate,
    database: Session = Depends(get_database),
) -> dict:
    packet = require_packet(database, packet_id)
    try:
        packet = mark_packet_handed_off(database, packet, handed_off_by=request.handed_off_by)
    except WorkPacketError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    record_event(
        database,
        "codex_packet_handed_off",
        actor=request.handed_off_by,
        client_id=packet.client_id,
        record_type="codex_work_packet",
        record_id=packet.id,
        details={"task_id": packet.task_id},
    )
    database.commit()
    database.refresh(packet)
    return {"packet": packet_response(packet), "handoff_text": render_handoff_text(packet)}


@router.post("/codex-work-packets/{packet_id}/result", response_model=schemas.CodexHandoffResultRead)
def submit_codex_handoff_result(
    packet_id: str,
    request: schemas.CodexHandoffResultCreate,
    database: Session = Depends(get_database),
) -> dict:
    packet = require_packet(database, packet_id)
    try:
        execution, reused_existing = record_codex_result(database, packet, request)
    except WorkPacketError as error:
        database.rollback()
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    record_event(
        database,
        "codex_handoff_result_recorded",
        actor=request.submitted_by,
        client_id=packet.client_id,
        record_type="execution",
        record_id=execution.id,
        details={"packet_id": packet.id, "task_id": packet.task_id, "outcome": execution.status, "reused": reused_existing},
    )
    database.commit()
    database.refresh(packet)
    database.refresh(execution)
    return {
        "packet": packet_response(packet),
        "execution": execution_response(execution),
        "reused_existing": reused_existing,
    }


@router.get("/dashboard/codex-work-packets/{packet_id}", response_class=HTMLResponse)
def codex_handoff_dashboard(
    packet_id: str,
    message: str = "",
    error: str = "",
    database: Session = Depends(get_database),
) -> HTMLResponse:
    packet = require_packet(database, packet_id)
    task = database.get(models.Task, packet.task_id)
    client = database.get(models.Client, packet.client_id)
    notice = f'<p class="form-notice success-notice">{escape(message)}</p>' if message else ""
    if error:
        notice = f'<p class="form-notice error-notice">{escape(error)}</p>'
    handoff_action = ""
    quality = packet_quality(packet)
    quality_rows_parts = []
    for item in quality["checks"]:
        remediation = (
            f' <span>{escape(str(item["remediation"]))}</span>'
            if item["status"] == "blocked"
            else ""
        )
        quality_rows_parts.append(
            f'<li><strong>{escape(str(item["key"]).replace("_", " "))}</strong> — '
            f'{escape(str(item["detail"]))}{remediation}</li>'
        )
    quality_rows = "".join(quality_rows_parts)
    quality_html = f'''<section class="workspace-note"><h2>Packet quality gate · {escape(quality["status"])}</h2><p>{quality["summary"]["passed"]} passed, {quality["summary"]["blocked"]} blocked.</p><ul class="report-list">{quality_rows}</ul></section>'''
    if packet.status == "generated":
        handoff_action = f'''<aside class="simulation-boundary"><strong>Ready to copy.</strong><span>Marking this handed off moves the approved task to running.</span><form method="post" action="/dashboard/codex-work-packets/{escape(packet.id)}/handoff"><input type="hidden" name="handed_off_by" value="Agency Owner"><button type="submit">Mark handed off to Codex</button></form></aside>'''
    result_form = ""
    content_review_form = ""
    if packet.status == "handed_off":
        example = json.dumps(
            {
                "operation_key": f"codex-result-{packet.id}",
                "outcome": "completed",
                "submitted_by": "Agency Owner",
                "summary": "Describe exactly what Codex completed.",
                "changed_files": [],
                "tests": [{"name": "build", "status": "passed", "detail": "Add the actual result"}],
                "commit_shas": [],
                "evidence": [],
                "blockers": [],
                "actual_cost": 0,
            },
            indent=2,
        )
        result_form = f'''<section class="workspace-note"><h2>Return Codex evidence</h2><p>Paste a structured result. Completed work will still wait for independent verification.</p><form method="post" action="/dashboard/codex-work-packets/{escape(packet.id)}/result"><label>Result JSON<textarea class="handoff-text" name="result_json" rows="18" required>{escape(example)}</textarea></label><button class="primary-button" type="submit">Record Codex result</button></form></section>'''
    elif packet.result_execution_id:
        result_form = f'''<section class="workspace-note"><h2>Result recorded</h2><p>Execution <code>{escape(packet.result_execution_id)}</code> is preserved. Completed work must be reviewed before verification.</p><a class="primary-action" href="/dashboard/verifications">Open verification queue</a></section>'''
        if (packet.packet_data or {}).get("local_seo_work_type") in {"local_page", "blog"}:
            existing_review = database.scalar(select(models.ContentReview).where(models.ContentReview.packet_id == packet.id))
            if existing_review is None or existing_review.status != "approved":
                checkbox_fields = "".join(
                    f'<label><input type="checkbox" name="{escape(key)}" value="true"> {escape(key.replace("_", " ").title())}</label>'
                    for key in CONTENT_REVIEW_CHECKS
                )
                content_review_form = f'''<section class="workspace-note"><h2>Human content review</h2><p>Complete every check before this content can be independently verified.</p><form method="post" action="/dashboard/codex-work-packets/{escape(packet.id)}/content-review"><input type="hidden" name="reviewer" value="Agency Owner"><input type="hidden" name="status" value="approved"><fieldset>{checkbox_fields}</fieldset><label>Review notes<textarea name="notes" rows="5" required></textarea></label><button class="primary-button" type="submit">Approve content review</button></form></section>'''
            else:
                content_review_form = f'''<section class="workspace-note"><h2>Human content review approved</h2><p>Reviewed by {escape(existing_review.reviewer or "Agency Owner")} on {escape(existing_review.decided_at.isoformat() if existing_review.decided_at else "")}. The execution can now enter independent verification.</p></section>'''
    page = HANDOFF_TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "{{PACKET_ID}}": escape(packet.id),
        "{{STATUS}}": escape(packet.status.replace("_", " ").title()),
        "{{CLIENT_NAME}}": escape(client.business_name if client else packet.client_id),
        "{{TASK_TITLE}}": escape(task.title if task else packet.task_id),
        "{{NOTICE}}": notice,
        "{{HANDOFF_ACTION}}": handoff_action,
        "{{HANDOFF_TEXT}}": escape(render_handoff_text(packet)),
        "{{RESULT_FORM}}": result_form,
        "{{QUALITY_GATE}}": quality_html,
        "{{CONTENT_REVIEW}}": content_review_form,
    }
    for source, replacement in replacements.items():
        page = page.replace(source, replacement)
    return HTMLResponse(page)


@router.post("/dashboard/codex-work-packets/{packet_id}/handoff", response_class=RedirectResponse)
async def codex_handoff_dashboard_submit(
    packet_id: str,
    request: Request,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    values = {key: entries[-1] for key, entries in parse_qs((await request.body()).decode(), keep_blank_values=True).items()}
    packet = require_packet(database, packet_id)
    actor = values.get("handed_off_by", "Agency Owner").strip() or "Agency Owner"
    try:
        mark_packet_handed_off(database, packet, handed_off_by=actor)
        record_event(database, "codex_packet_handed_off", actor=actor, client_id=packet.client_id, record_type="codex_work_packet", record_id=packet.id, details={"task_id": packet.task_id})
        database.commit()
    except WorkPacketError as caught:
        database.rollback()
        return RedirectResponse(url=f"/dashboard/codex-work-packets/{packet.id}?error={quote(caught.detail)}", status_code=303)
    return RedirectResponse(url=f"/dashboard/codex-work-packets/{packet.id}?message={quote('Packet handed off; task is now running.')}", status_code=303)


@router.post("/dashboard/codex-work-packets/{packet_id}/content-review", response_class=RedirectResponse)
async def content_review_dashboard_submit(
    packet_id: str,
    request: Request,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    values = {key: entries[-1] for key, entries in parse_qs((await request.body()).decode(), keep_blank_values=True).items()}
    checklist = {key: values.get(key, "").casefold() == "true" for key in CONTENT_REVIEW_CHECKS}
    try:
        record_content_review(
            packet_id,
            schemas.ContentReviewCreate(
                reviewer=values.get("reviewer", "Agency Owner"),
                status=values.get("status", "approved"),
                checklist=checklist,
                notes=values.get("notes", ""),
            ),
            database,
        )
    except (HTTPException, ValidationError, ValueError) as caught:
        detail = getattr(caught, "detail", None) or str(caught)
        database.rollback()
        return RedirectResponse(url=f"/dashboard/codex-work-packets/{packet_id}?error={quote(str(detail))}", status_code=303)
    return RedirectResponse(
        url=f"/dashboard/codex-work-packets/{packet_id}?message={quote('Human content review recorded.')}",
        status_code=303,
    )


@router.post("/dashboard/codex-work-packets/{packet_id}/result", response_class=RedirectResponse)
async def codex_result_dashboard_submit(
    packet_id: str,
    request: Request,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    values = {key: entries[-1] for key, entries in parse_qs((await request.body()).decode(), keep_blank_values=True).items()}
    packet = require_packet(database, packet_id)
    try:
        payload = json.loads(values.get("result_json", ""))
        result_request = schemas.CodexHandoffResultCreate.model_validate(payload)
        execution, reused = record_codex_result(database, packet, result_request)
        record_event(database, "codex_handoff_result_recorded", actor=result_request.submitted_by, client_id=packet.client_id, record_type="execution", record_id=execution.id, details={"packet_id": packet.id, "task_id": packet.task_id, "outcome": execution.status, "reused": reused})
        database.commit()
    except (json.JSONDecodeError, ValidationError, WorkPacketError) as caught:
        database.rollback()
        detail = getattr(caught, "detail", str(caught))
        return RedirectResponse(url=f"/dashboard/codex-work-packets/{packet.id}?error={quote(detail)}", status_code=303)
    return RedirectResponse(url=f"/dashboard/codex-work-packets/{packet.id}?message={quote(f'Codex result {execution.status} recorded as {execution.id}.')}", status_code=303)


@router.get("/clients/{client_id}/codex-work-packets", response_model=list[schemas.CodexWorkPacketRead])
def list_client_work_packets(client_id: str, database: Session = Depends(get_database)) -> list[dict]:
    if database.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    packets = list(
        database.scalars(
            select(models.CodexWorkPacket)
            .where(models.CodexWorkPacket.client_id == client_id)
            .order_by(models.CodexWorkPacket.created_at.desc(), models.CodexWorkPacket.id.desc())
        )
    )
    return [packet_response(packet) for packet in packets]


@router.post(
    "/clients/{client_id}/website-generation-task",
    response_model=schemas.TaskRead,
    status_code=status.HTTP_201_CREATED,
)
def request_website_generation(
    client_id: str,
    request: schemas.WebsiteGenerationTaskCreate,
    database: Session = Depends(get_database),
) -> dict:
    """Turn approved onboarding facts into an explicit approval-required build task."""
    client = database.get(models.Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    profile = database.scalar(
        select(models.OfficialProfile).where(models.OfficialProfile.client_id == client_id)
    )
    if profile is None:
        raise HTTPException(status_code=409, detail="An official client profile is required before requesting website generation")
    intake = database.scalar(
        select(models.Intake)
        .where(models.Intake.client_id == client_id)
        .order_by(models.Intake.submitted_at.desc())
    )
    if intake is None or not intake.domain:
        raise HTTPException(status_code=409, detail="A saved client domain is required before requesting website generation")
    existing = database.scalar(
        select(models.Task).join(models.Finding, models.Finding.id == models.Task.source_finding_id).where(
            models.Task.client_id == client_id,
            models.Finding.rule_key == "website_generation_requested",
            models.Task.status.in_(["proposed", "approved", "ready", "running", "blocked"]),
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Active website-generation task already exists: {existing.id}")
    finding = models.Finding(
        client_id=client_id,
        rule_key="website_generation_requested",
        title="Website generation requested",
        explanation="An approved client profile is ready for an agency-owner website-generation decision.",
        evidence={"official_profile_id": profile.id, "approved_version_id": profile.approved_version_id, "domain": intake.domain, "mode": request.mode},
        source="approved_onboarding",
        severity="medium",
        confidence="high",
        recommended_action="Review and approve the scoped website-generation task before repository work begins.",
        status="open",
    )
    database.add(finding)
    database.flush()
    task = models.Task(
        client_id=client_id,
        source_finding_id=finding.id,
        title=f"{request.mode.replace('_', ' ').title()} website for {client.business_name}",
        requested_outcome=request.requested_outcome,
        reason="Requested from the approved onboarding profile.",
        expected_result="Verify the generated website meets the approved scope and is live on the client domain.",
        success_metric="Production URL, changed-file audit, build checks, and independent verification",
        verification_window="Verify immediately after handoff and compare site/indexing signals over the next 30 days",
        estimated_effort="Website build; estimate after repository review",
        risk="high",
        required_access=["GitHub repository", "Vercel project", "client domain"],
        status="proposed",
    )
    database.add(task)
    database.flush()
    database.add(models.TaskStatusEvent(client_id=client_id, task_id=task.id, from_status=None, to_status="proposed", changed_by=request.requested_by, reason="Website generation requested from approved onboarding"))
    notify_task_approval(database, task)
    database.commit()
    database.refresh(task)
    from app.routes.tasks import task_response
    return task_response(database, task)
