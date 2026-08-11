"""Phase 8 safe fulfillment simulator and demo workflow."""

from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, quote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_database
from app.fulfillment_simulator import FakeFulfillmentExecutor
from app.notification_service import notify_execution_result
from app.routes.tasks import add_status_event, ensure_dependencies_verified, require_active_client, require_client, require_task
from app.subscription_service import require_fulfillment_entitlement


router = APIRouter(tags=["fulfillment simulator"])
TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "fulfillment_demo.html"
ELIGIBLE_TASK_STATUSES = {"approved", "ready"}


def execution_response(execution: models.FulfillmentExecution, reused_existing: bool = False) -> dict:
    return {
        "id": execution.id,
        "operation_key": execution.operation_key,
        "client_id": execution.client_id,
        "task_id": execution.task_id,
        "status": execution.status,
        "intended_actions": execution.intended_actions,
        "simulated_changed_files": execution.simulated_changed_files,
        "simulated_test_results": execution.simulated_test_results,
        "evidence": execution.evidence,
        "estimated_cost": execution.estimated_cost,
        "attempt_count": execution.attempt_count,
        "retry_delays_seconds": execution.retry_delays_seconds,
        "failure_type": execution.failure_type,
        "error_message": execution.error_message,
        "started_at": execution.started_at,
        "completed_at": execution.completed_at,
        "reused_existing": reused_existing,
    }


def run_simulation(
    database: Session,
    task_id: str,
    request: schemas.SimulatedExecutionCreate,
) -> tuple[models.FulfillmentExecution, bool]:
    """Authorize, run, and permanently record one fake operation."""
    existing = database.scalar(
        select(models.FulfillmentExecution).where(
            models.FulfillmentExecution.operation_key == request.operation_key
        )
    )
    if existing is not None:
        if existing.task_id != task_id:
            raise HTTPException(status_code=409, detail="Operation key already belongs to another task")
        return existing, True

    task = require_task(database, task_id)
    require_active_client(database, task.client_id)
    require_fulfillment_entitlement(database, task.client_id)
    if task.status not in ELIGIBLE_TASK_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Simulator requires an approved or ready task; task is {task.status}",
        )

    executor = FakeFulfillmentExecutor()
    try:
        result = executor.execute(task, request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if task.status == "approved":
        ensure_dependencies_verified(database, task)
        add_status_event(database, task, "approved", "ready", "fulfillment simulator", "Dependencies checked")
        task.status = "ready"

    started_at = datetime.utcnow()
    add_status_event(database, task, "ready", "running", "fulfillment simulator", "Demo execution started")
    task.status = "running"

    execution = models.FulfillmentExecution(
        operation_key=request.operation_key,
        client_id=task.client_id,
        task_id=task.id,
        status=result.status,
        intended_actions=result.intended_actions,
        simulated_changed_files=result.simulated_changed_files,
        simulated_test_results=result.simulated_test_results,
        evidence={**result.evidence, "task_id": task.id, "client_id": task.client_id},
        estimated_cost=request.estimated_cost,
        attempt_count=result.attempt_count,
        retry_delays_seconds=result.retry_delays_seconds,
        failure_type=result.failure_type,
        error_message=result.error_message,
        started_at=started_at,
        completed_at=datetime.utcnow(),
    )
    database.add(execution)
    database.flush()
    notify_execution_result(database, execution, task)
    add_status_event(
        database,
        task,
        "running",
        result.status,
        "fulfillment simulator",
        result.error_message or "Demo execution finished; verification is still separate",
    )
    task.status = result.status
    database.commit()
    database.refresh(execution)
    return execution, False


@router.post(
    "/tasks/{task_id}/simulated-executions",
    response_model=schemas.SimulatedExecutionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_simulated_execution(
    task_id: str,
    request: schemas.SimulatedExecutionCreate,
    database: Session = Depends(get_database),
) -> dict:
    execution, reused = run_simulation(database, task_id, request)
    return execution_response(execution, reused)


@router.get("/executions/{execution_id}", response_model=schemas.SimulatedExecutionRead)
def read_execution(
    execution_id: str,
    database: Session = Depends(get_database),
) -> dict:
    execution = database.get(models.FulfillmentExecution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution_response(execution)


@router.get(
    "/clients/{client_id}/executions",
    response_model=list[schemas.SimulatedExecutionRead],
)
def list_client_executions(
    client_id: str,
    database: Session = Depends(get_database),
) -> list[dict]:
    require_client(database, client_id)
    executions = list(
        database.scalars(
            select(models.FulfillmentExecution)
            .where(models.FulfillmentExecution.client_id == client_id)
            .order_by(models.FulfillmentExecution.started_at, models.FulfillmentExecution.id)
        )
    )
    return [execution_response(execution) for execution in executions]


def render_eligible_task(database: Session, task: models.Task) -> str:
    client = database.get(models.Client, task.client_id)
    operation_key = f"demo-{task.id}-{uuid4().hex[:10]}"
    return f"""
      <article class="simulation-task">
        <header><div><span>{escape(client.business_name)} · {escape(task.status)}</span><h2>{escape(task.title)}</h2></div><code>{escape(task.id)}</code></header>
        <p><strong>Requested outcome</strong>{escape(task.requested_outcome)}</p>
        <form method="post" action="/dashboard/tasks/{escape(task.id)}/simulate">
          <label>Demo outcome<select name="outcome"><option value="success">Success</option><option value="failure">Failure</option><option value="blocked">Blocked</option></select></label>
          <label>Failure type<select name="failure_type"><option value="">Not applicable</option><option value="temporary">Temporary</option><option value="permanent">Permanent</option></select></label>
          <label>Temporary failures before success<select name="temporary_failures_before_result"><option>0</option><option>1</option><option>2</option><option>3</option></select></label>
          <label>Estimated cost<input name="estimated_cost" type="number" min="0" max="10000" step="0.01" value="0.25" required></label>
          <label class="operation-key">Unique operation key<input name="operation_key" value="{escape(operation_key)}" required></label>
          <button type="submit">Run safe simulation</button>
        </form>
      </article>
    """


def render_execution(database: Session, execution: models.FulfillmentExecution) -> str:
    task = database.get(models.Task, execution.task_id)
    client = database.get(models.Client, execution.client_id)
    retries = ", ".join(f"{seconds}s" for seconds in execution.retry_delays_seconds) or "None"
    files = ", ".join(execution.simulated_changed_files) or "None"
    return f"""
      <article class="execution-row status-{escape(execution.status)}">
        <div><span>{escape(client.business_name)} · {escape(execution.status)}</span><h3>{escape(task.title)}</h3><code>{escape(execution.operation_key)}</code></div>
        <dl><div><dt>Attempts</dt><dd>{execution.attempt_count}</dd></div><div><dt>Retry schedule</dt><dd>{escape(retries)}</dd></div><div><dt>Recorded cost</dt><dd>${execution.estimated_cost:.2f}</dd></div><div><dt>Changed files</dt><dd>{escape(files)}</dd></div></dl>
      </article>
    """


def render_codex_packet(database: Session, packet: models.CodexWorkPacket) -> str:
    task = database.get(models.Task, packet.task_id)
    client = database.get(models.Client, packet.client_id)
    return f'''
      <article class="execution-row status-{escape(packet.status)}">
        <div><span>{escape(client.business_name)} · {escape(packet.status.replace("_", " "))}</span><h3>{escape(task.title)}</h3><code>{escape(packet.id)}</code></div>
        <dl><div><dt>Mode</dt><dd>{escape(packet.mode)}</dd></div><div><dt>Repository</dt><dd>{escape(packet.repository_name)}</dd></div><div><dt>Expires</dt><dd>{packet.expires_at.strftime("%b %d")}</dd></div><div><dt>Result</dt><dd>{escape(packet.result_execution_id or "Waiting")}</dd></div></dl>
        <a class="primary-action" href="/dashboard/codex-work-packets/{escape(packet.id)}">Open handoff</a>
      </article>'''


@router.get("/dashboard/fulfillment", response_class=HTMLResponse)
def fulfillment_demo(
    database: Session = Depends(get_database),
    message: str = "",
    error: str = "",
) -> HTMLResponse:
    tasks = list(
        database.scalars(
            select(models.Task)
            .where(models.Task.status.in_(ELIGIBLE_TASK_STATUSES))
            .order_by(models.Task.proposed_at, models.Task.id)
        )
    )
    executions = list(
        database.scalars(
            select(models.FulfillmentExecution)
            .order_by(models.FulfillmentExecution.started_at.desc())
            .limit(20)
        )
    )
    packets = list(
        database.scalars(
            select(models.CodexWorkPacket)
            .order_by(models.CodexWorkPacket.created_at.desc(), models.CodexWorkPacket.id.desc())
            .limit(30)
        )
    )
    task_rows = "".join(render_eligible_task(database, task) for task in tasks)
    if not task_rows:
        task_rows = '<p class="approval-empty">No approved or ready tasks are available to simulate.</p>'
    result_rows = "".join(render_execution(database, execution) for execution in executions)
    if not result_rows:
        result_rows = '<p class="approval-empty">No simulated executions have been recorded.</p>'
    packet_rows = "".join(render_codex_packet(database, packet) for packet in packets)
    if not packet_rows:
        packet_rows = '<p class="approval-empty">No Codex handoff packets are ready yet. Approve an eligible connected website or SEO task first.</p>'
    notice = f'<p class="form-notice success-notice">{escape(message)}</p>' if message else ""
    if error:
        notice = f'<p class="form-notice error-notice">{escape(error)}</p>'
    page = TEMPLATE_PATH.read_text(encoding="utf-8")
    page = page.replace("{{ELIGIBLE_COUNT}}", str(len(tasks)))
    page = page.replace("{{PACKET_COUNT}}", str(len(packets))).replace("{{PACKETS}}", packet_rows)
    page = page.replace("{{TASKS}}", task_rows).replace("{{EXECUTIONS}}", result_rows)
    page = page.replace("{{NOTICE}}", notice)
    return HTMLResponse(page)


@router.post("/dashboard/tasks/{task_id}/simulate", response_class=RedirectResponse)
async def fulfillment_demo_submit(
    task_id: str,
    request: Request,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    encoded = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    values = {key: entries[-1] for key, entries in encoded.items()}
    try:
        simulation = schemas.SimulatedExecutionCreate(
            operation_key=values.get("operation_key", ""),
            outcome=values.get("outcome", ""),
            failure_type=values.get("failure_type") or None,
            temporary_failures_before_result=values.get("temporary_failures_before_result", "0"),
            estimated_cost=values.get("estimated_cost", "0.25"),
        )
        execution, reused = run_simulation(database, task_id, simulation)
    except (HTTPException, ValidationError) as exc:
        database.rollback()
        detail = getattr(exc, "detail", str(exc))
        return RedirectResponse(url=f"/dashboard/fulfillment?error={quote(str(detail))}", status_code=303)
    message = f"Simulation {execution.status}. " + ("Existing result reused." if reused else "No external work occurred.")
    return RedirectResponse(url=f"/dashboard/fulfillment?message={quote(message)}", status_code=303)
