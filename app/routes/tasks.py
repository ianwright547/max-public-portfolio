"""Phase 7 evidence-backed task proposals and human approval."""

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.agency_access_service import require_client_operations_access
from app.database import get_database
from app.notification_service import notify_task_approval
from app.task_rules import ACTIVE_TASK_STATUSES, validate_transition

router = APIRouter(tags=["tasks"])
TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "task_approvals.html"


def require_client(database: Session, client_id: str) -> models.Client:
    client = database.get(models.Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def require_active_client(database: Session, client_id: str) -> models.Client:
    client = require_client(database, client_id)
    if client.archived_at is not None or client.status == "archived":
        raise HTTPException(status_code=409, detail="Archived clients cannot receive new work")
    return client


def require_task(database: Session, task_id: str) -> models.Task:
    task = database.get(models.Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def dependency_ids(database: Session, task_id: str) -> list[str]:
    return list(
        database.scalars(
            select(models.TaskDependency.depends_on_task_id)
            .where(models.TaskDependency.task_id == task_id)
            .order_by(models.TaskDependency.id)
        )
    )


def task_response(database: Session, task: models.Task) -> dict:
    decisions = list(
        database.scalars(
            select(models.TaskDecision)
            .where(
                models.TaskDecision.client_id == task.client_id,
                models.TaskDecision.task_id == task.id,
            )
            .order_by(models.TaskDecision.decided_at, models.TaskDecision.id)
        )
    )
    measurements = list(
        database.scalars(
            select(models.OutcomeMeasurement)
            .where(
                models.OutcomeMeasurement.client_id == task.client_id,
                models.OutcomeMeasurement.task_id == task.id,
            )
            .order_by(models.OutcomeMeasurement.observed_at, models.OutcomeMeasurement.id)
        )
    )
    return {
        "id": task.id,
        "client_id": task.client_id,
        "source_finding_id": task.source_finding_id,
        "title": task.title,
        "requested_outcome": task.requested_outcome,
        "reason": task.reason,
        "expected_result": task.expected_result,
        "success_metric": task.success_metric,
        "verification_window": task.verification_window,
        "estimated_effort": task.estimated_effort,
        "risk": task.risk,
        "required_access": task.required_access,
        "browser_control_approved_by": task.browser_control_approved_by,
        "browser_control_approved_at": task.browser_control_approved_at,
        "browser_control_approval_reason": task.browser_control_approval_reason,
        "dependency_ids": dependency_ids(database, task.id),
        "status": task.status,
        "proposed_at": task.proposed_at,
        "approval_information": decisions,
        "outcome_measurements": [
            {
                "id": item.id,
                "operation_key": item.operation_key,
                "client_id": item.client_id,
                "task_id": item.task_id,
                "execution_id": item.execution_id,
                "metric_name": item.metric_name,
                "baseline_value": item.baseline_value,
                "observed_value": item.observed_value,
                "unit": item.unit,
                "assessment": item.assessment,
                "source_type": item.source_type,
                "source_reference": item.source_reference,
                "evidence": item.evidence,
                "notes": item.notes,
                "recorded_by": item.recorded_by,
                "observed_at": item.observed_at,
                "created_at": item.created_at,
            }
            for item in measurements
        ],
    }


def validate_dependencies(database: Session, client_id: str, ids: list[str]) -> list[models.Task]:
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="A dependency can only be listed once")
    dependencies = []
    for dependency_id in ids:
        dependency = require_task(database, dependency_id)
        if dependency.client_id != client_id:
            raise HTTPException(status_code=409, detail="Task dependencies must belong to the same client")
        dependencies.append(dependency)
    return dependencies


def add_status_event(
    database: Session,
    task: models.Task,
    from_status: Optional[str],
    to_status: str,
    changed_by: str,
    reason: Optional[str] = None,
) -> None:
    database.add(
        models.TaskStatusEvent(
            client_id=task.client_id,
            task_id=task.id,
            from_status=from_status,
            to_status=to_status,
            changed_by=changed_by,
            reason=reason,
            changed_at=datetime.utcnow(),
        )
    )


@router.post(
    "/clients/{client_id}/tasks",
    response_model=schemas.TaskRead,
    status_code=status.HTTP_201_CREATED,
)
def propose_task(
    client_id: str,
    proposal: schemas.TaskCreate,
    database: Session = Depends(get_database),
    _agency_identity: str = Depends(require_client_operations_access),
) -> dict:
    """Draft one task from an open finding; do not approve or execute it."""
    require_active_client(database, client_id)
    finding = database.get(models.Finding, proposal.source_finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    if finding.client_id != client_id:
        raise HTTPException(status_code=409, detail="Finding belongs to a different client")
    if finding.status != "open" or not finding.evidence or not finding.recommended_action:
        raise HTTPException(status_code=409, detail="Task requires an open, evidence-backed finding")

    duplicate = database.scalar(
        select(models.Task).where(
            models.Task.client_id == client_id,
            models.Task.source_finding_id == finding.id,
            models.Task.status.in_(ACTIVE_TASK_STATUSES),
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail=f"Active task already exists: {duplicate.id}")

    dependencies = validate_dependencies(database, client_id, proposal.dependency_ids)
    task = models.Task(
        client_id=client_id,
        source_finding_id=finding.id,
        title=proposal.title,
        requested_outcome=proposal.requested_outcome,
        reason=proposal.reason,
        expected_result=proposal.expected_result,
        success_metric=proposal.success_metric,
        verification_window=proposal.verification_window,
        estimated_effort=proposal.estimated_effort,
        risk=proposal.risk,
        required_access=proposal.required_access,
        status="proposed",
    )
    database.add(task)
    database.flush()
    for dependency in dependencies:
        if dependency.id == task.id:
            raise HTTPException(status_code=422, detail="A task cannot depend on itself")
        database.add(
            models.TaskDependency(
                client_id=client_id,
                task_id=task.id,
                depends_on_task_id=dependency.id,
            )
        )
    add_status_event(database, task, None, "proposed", "system", "Proposed from an evidence-backed finding")
    notify_task_approval(database, task)
    database.commit()
    database.refresh(task)
    return task_response(database, task)


@router.get("/tasks/pending-approval", response_model=list[schemas.TaskRead])
def pending_tasks(database: Session = Depends(get_database)) -> list[dict]:
    tasks = list(
        database.scalars(
            select(models.Task)
            .where(models.Task.status == "proposed")
            .order_by(models.Task.proposed_at, models.Task.id)
        )
    )
    return [task_response(database, task) for task in tasks]


@router.get("/clients/{client_id}/tasks", response_model=list[schemas.TaskRead])
def list_client_tasks(client_id: str, database: Session = Depends(get_database)) -> list[dict]:
    require_client(database, client_id)
    tasks = list(
        database.scalars(
            select(models.Task)
            .where(models.Task.client_id == client_id)
            .order_by(models.Task.proposed_at, models.Task.id)
        )
    )
    return [task_response(database, task) for task in tasks]


@router.get("/tasks/{task_id}", response_model=schemas.TaskRead)
def read_task(task_id: str, database: Session = Depends(get_database)) -> dict:
    return task_response(database, require_task(database, task_id))


@router.post(
    "/tasks/{task_id}/outcomes",
    response_model=schemas.OutcomeMeasurementRead,
    status_code=status.HTTP_201_CREATED,
)
def record_outcome_measurement(
    task_id: str,
    measurement: schemas.OutcomeMeasurementCreate,
    database: Session = Depends(get_database),
) -> dict:
    """Persist one idempotent, source-backed post-work outcome measurement."""
    task = require_task(database, task_id)
    client = require_client(database, task.client_id)
    if client.archived_at is not None or client.status == "archived":
        raise HTTPException(status_code=409, detail="Archived clients cannot receive outcome measurements")
    if task.status not in {"completed", "verified", "failed", "blocked"}:
        raise HTTPException(status_code=409, detail="Outcome measurement requires an executed task")
    if not measurement.evidence or any(not item.strip() for item in measurement.evidence):
        raise HTTPException(status_code=422, detail="Outcome evidence cannot contain blank entries")
    if measurement.execution_id is not None:
        execution = database.get(models.FulfillmentExecution, measurement.execution_id)
        if execution is None or execution.task_id != task.id or execution.client_id != task.client_id:
            raise HTTPException(status_code=409, detail="Outcome execution must belong to this task and client")
    existing = database.scalar(
        select(models.OutcomeMeasurement).where(
            models.OutcomeMeasurement.operation_key == measurement.operation_key
        )
    )
    if existing is not None:
        if existing.task_id != task.id:
            raise HTTPException(status_code=409, detail="Outcome operation key belongs to another task")
        response = {
            **{key: getattr(existing, key) for key in (
                "id", "operation_key", "client_id", "task_id", "execution_id", "metric_name",
                "baseline_value", "observed_value", "unit", "assessment", "source_type",
                "source_reference", "evidence", "notes", "recorded_by", "observed_at", "created_at",
            )},
            "reused_existing": True,
        }
        return response
    row = models.OutcomeMeasurement(
        operation_key=measurement.operation_key,
        client_id=task.client_id,
        task_id=task.id,
        execution_id=measurement.execution_id,
        metric_name=measurement.metric_name,
        baseline_value=measurement.baseline_value,
        observed_value=measurement.observed_value,
        unit=measurement.unit,
        assessment=measurement.assessment,
        source_type=measurement.source_type,
        source_reference=measurement.source_reference,
        evidence=measurement.evidence,
        notes=measurement.notes,
        recorded_by=measurement.recorded_by,
        observed_at=measurement.observed_at,
    )
    database.add(row)
    database.commit()
    database.refresh(row)
    return {
        **{key: getattr(row, key) for key in (
            "id", "operation_key", "client_id", "task_id", "execution_id", "metric_name",
            "baseline_value", "observed_value", "unit", "assessment", "source_type",
            "source_reference", "evidence", "notes", "recorded_by", "observed_at", "created_at",
        )},
        "reused_existing": False,
    }


@router.get("/tasks/{task_id}/outcomes", response_model=list[schemas.OutcomeMeasurementRead])
def list_outcome_measurements(
    task_id: str,
    database: Session = Depends(get_database),
) -> list[dict]:
    task = require_task(database, task_id)
    return task_response(database, task)["outcome_measurements"]


def decide_task(database: Session, task: models.Task, decision: schemas.TaskDecisionCreate) -> dict:
    validate_transition(task.status, decision.decision)
    if decision.decision == "rejected" and not (decision.reason or "").strip():
        raise HTTPException(status_code=422, detail="A rejection reason is required")

    old_status = task.status
    task.status = decision.decision
    saved_decision = models.TaskDecision(
        client_id=task.client_id,
        task_id=task.id,
        decision=decision.decision,
        decision_maker=decision.decision_maker,
        reason=decision.reason,
    )
    database.add(saved_decision)
    add_status_event(
        database,
        task,
        old_status,
        decision.decision,
        decision.decision_maker,
        decision.reason,
    )
    database.flush()
    if decision.decision == "approved":
        _prepare_codex_packet_after_approval(database, task, saved_decision)
    database.commit()
    database.refresh(task)
    return task_response(database, task)


def approve_browser_control(
    database: Session, task: models.Task, approval: schemas.BrowserControlApprovalCreate
) -> dict:
    """Record explicit owner permission for browser work on one approved task."""
    if task.status not in {"approved", "ready"}:
        raise HTTPException(
            status_code=409,
            detail=f"Browser control requires an approved or ready task; task is {task.status}",
        )
    if task.browser_control_approved_at is None:
        task.browser_control_approved_by = approval.approved_by
        task.browser_control_approved_at = datetime.utcnow()
        task.browser_control_approval_reason = approval.reason
        database.add(
            models.TaskDecision(
                client_id=task.client_id,
                task_id=task.id,
                decision="browser_approved",
                decision_maker=approval.approved_by,
                reason=approval.reason,
            )
        )
        add_status_event(
            database,
            task,
            task.status,
            task.status,
            approval.approved_by,
            f"Browser-control scope approved: {approval.reason}",
        )
        database.commit()
        database.refresh(task)
    return task_response(database, task)


@router.post(
    "/tasks/{task_id}/browser-approval",
    response_model=schemas.TaskRead,
)
def approve_task_browser_control(
    task_id: str,
    approval: schemas.BrowserControlApprovalCreate,
    database: Session = Depends(get_database),
) -> dict:
    return approve_browser_control(database, require_task(database, task_id), approval)


def _prepare_codex_packet_after_approval(
    database: Session,
    task: models.Task,
    decision: models.TaskDecision,
) -> None:
    """Create a zero-model-cost handoff when this approved task is already connected."""
    from app.audit import record_event
    from app.codex_packet_service import (
        WorkPacketError,
        infer_seo_work_type,
        prepare_connected_work_packet,
    )

    work_type = infer_seo_work_type(task)
    if work_type == "general":
        return
    repository = database.scalar(
        select(models.GitHubRepositoryConnection).where(
            models.GitHubRepositoryConnection.client_id == task.client_id,
            models.GitHubRepositoryConnection.connection_status.in_({"linked", "connected"}),
        )
    )
    website = database.scalar(
        select(models.WebsiteConnection).where(
            models.WebsiteConnection.client_id == task.client_id,
            models.WebsiteConnection.connection_status.in_({"linked", "connected"}),
        )
    )
    if repository is None or website is None:
        return
    try:
        packet, reused = prepare_connected_work_packet(
            database,
            task.id,
            schemas.ConnectedCodexPacketCreate(
                operation_key=f"approved-task-{task.id}",
                created_by=decision.decision_maker,
                mode="repair" if work_type == "technical_seo" else "improve",
                seo_work_type=work_type,
                publish_allowed=False,
                task_specific_instructions="Automatically prepared after explicit task approval; handoff still requires a separate action.",
            ),
        )
    except WorkPacketError:
        return
    record_event(
        database,
        "codex_packet_auto_prepared",
        actor=decision.decision_maker,
        client_id=task.client_id,
        record_type="codex_work_packet",
        record_id=packet.id,
        details={"task_id": task.id, "decision_id": decision.id, "reused": reused},
    )


@router.post("/tasks/{task_id}/decision", response_model=schemas.TaskRead)
def record_task_decision(
    task_id: str,
    decision: schemas.TaskDecisionCreate,
    database: Session = Depends(get_database),
    _agency_identity: str = Depends(require_client_operations_access),
) -> dict:
    return decide_task(database, require_task(database, task_id), decision)


def ensure_dependencies_verified(database: Session, task: models.Task) -> None:
    unverified = []
    for dependency_id in dependency_ids(database, task.id):
        dependency = require_task(database, dependency_id)
        if dependency.client_id != task.client_id:
            raise HTTPException(status_code=409, detail="Cross-client dependency detected")
        if dependency.status != "verified":
            unverified.append(dependency.id)
    if unverified:
        raise HTTPException(
            status_code=409,
            detail=f"Dependencies must be verified first: {', '.join(unverified)}",
        )


@router.post("/tasks/{task_id}/status", response_model=schemas.TaskRead)
def change_task_status(
    task_id: str,
    change: schemas.TaskStatusChange,
    database: Session = Depends(get_database),
    _agency_identity: str = Depends(require_client_operations_access),
) -> dict:
    """Record a valid state change; this function never executes external work."""
    task = require_task(database, task_id)
    validate_transition(task.status, change.target_status)
    if change.target_status == "ready":
        ensure_dependencies_verified(database, task)
    if change.target_status in {"blocked", "failed", "verified"} and not (change.reason or "").strip():
        raise HTTPException(status_code=422, detail=f"A reason is required for {change.target_status}")

    old_status = task.status
    task.status = change.target_status
    add_status_event(database, task, old_status, change.target_status, change.changed_by, change.reason)
    database.commit()
    database.refresh(task)
    return task_response(database, task)


def render_pending_task(database: Session, task: models.Task) -> str:
    finding = database.get(models.Finding, task.source_finding_id)
    client = database.get(models.Client, task.client_id)
    evidence = " · ".join(f"{key.replace('_', ' ')}: {value}" for key, value in finding.evidence.items())
    access = ", ".join(task.required_access) if task.required_access else "None specified"
    dependencies = ", ".join(dependency_ids(database, task.id)) or "None"
    return f"""
      <article class="approval-task" data-task-id="{escape(task.id)}">
        <header><div><span class="approval-label">{escape(client.business_name)} · {escape(task.risk)} risk · {escape(task.estimated_effort)}</span><h2>{escape(task.title)}</h2></div><code>{escape(task.id)}</code></header>
        <p class="task-outcome"><strong>Requested outcome</strong>{escape(task.requested_outcome)}</p>
        <div class="approval-evidence"><div><span>Expected result</span><p>{escape(task.expected_result)}</p></div><div><span>Success metric</span><p>{escape(task.success_metric)}</p></div><div><span>Verification window</span><p>{escape(task.verification_window)}</p></div></div>
        <div class="approval-evidence"><div><span>Why</span><p>{escape(task.reason)}</p></div><div><span>Finding evidence</span><p>{escape(evidence)}</p></div></div>
        <dl><div><dt>Source finding</dt><dd>{escape(finding.title)}</dd></div><div><dt>Required access</dt><dd>{escape(access)}</dd></div><div><dt>Dependencies</dt><dd>{escape(dependencies)}</dd></div></dl>
        <div class="decision-actions">
          <form method="post" action="/dashboard/tasks/{escape(task.id)}/decision">
            <input type="hidden" name="decision" value="approved">
            <label>Decision maker<input name="decision_maker" required placeholder="Your name"></label>
            <button type="submit">Approve task</button>
          </form>
          <form method="post" action="/dashboard/tasks/{escape(task.id)}/decision" class="reject-form">
            <input type="hidden" name="decision" value="rejected">
            <label>Decision maker<input name="decision_maker" required placeholder="Your name"></label>
            <label>Rejection reason<input name="reason" required placeholder="Why should this not proceed?"></label>
            <button type="submit">Reject task</button>
          </form>
        </div>
      </article>
    """


@router.get("/dashboard/tasks/approvals", response_class=HTMLResponse)
def approval_dashboard(database: Session = Depends(get_database), message: str = "", error: str = "") -> HTMLResponse:
    tasks = list(
        database.scalars(
            select(models.Task)
            .where(models.Task.status == "proposed")
            .order_by(models.Task.proposed_at, models.Task.id)
        )
    )
    rows = "".join(render_pending_task(database, task) for task in tasks)
    if not rows:
        rows = '<p class="approval-empty">No task proposals are waiting for approval.</p>'
    notice = f'<p class="form-notice success-notice">{escape(message)}</p>' if message else ""
    if error:
        notice = f'<p class="form-notice error-notice">{escape(error)}</p>'
    page = TEMPLATE_PATH.read_text(encoding="utf-8")
    page = page.replace("{{PENDING_COUNT}}", str(len(tasks))).replace("{{TASKS}}", rows).replace("{{NOTICE}}", notice)
    return HTMLResponse(page)


@router.post("/dashboard/tasks/{task_id}/decision", response_class=RedirectResponse)
async def approval_dashboard_decision(
    task_id: str,
    request: Request,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    encoded = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    values = {key: entries[-1] for key, entries in encoded.items()}
    try:
        decision = schemas.TaskDecisionCreate(
            decision=values.get("decision", ""),
            decision_maker=values.get("decision_maker", ""),
            reason=values.get("reason") or None,
        )
        decide_task(database, require_task(database, task_id), decision)
    except (HTTPException, ValidationError) as exc:
        database.rollback()
        detail = getattr(exc, "detail", str(exc))
        return RedirectResponse(url=f"/dashboard/tasks/approvals?error={quote(str(detail))}", status_code=303)
    label = "approved" if decision.decision == "approved" else "rejected"
    return RedirectResponse(url=f"/dashboard/tasks/approvals?message={quote(f'Task {label}. No work was started.')}", status_code=303)
