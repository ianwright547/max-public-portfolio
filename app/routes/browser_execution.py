"""Approval-gated browser fallback through an external worker."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.browser_execution_service import BrowserExecutionError, BrowserWorkerAdapter
from app.database import get_database
from app.routes.fulfillment import execution_response
from app.routes.tasks import add_status_event, ensure_dependencies_verified, require_active_client, require_task
from app.subscription_service import require_fulfillment_entitlement


router = APIRouter(tags=["browser execution"])


def _execution_or_404(database: Session, execution_id: str) -> models.FulfillmentExecution:
    execution = database.get(models.FulfillmentExecution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


@router.post("/tasks/{task_id}/browser-executions", response_model=schemas.SimulatedExecutionRead, status_code=status.HTTP_201_CREATED)
def submit_browser_execution(task_id: str, request: schemas.BrowserExecutionCreate, database: Session = Depends(get_database)) -> dict:
    existing = database.scalar(select(models.FulfillmentExecution).where(models.FulfillmentExecution.operation_key == request.operation_key))
    if existing is not None:
        if existing.task_id != task_id:
            raise HTTPException(status_code=409, detail="Operation key already belongs to another task")
        return execution_response(existing, True)
    task = require_task(database, task_id)
    require_active_client(database, task.client_id)
    require_fulfillment_entitlement(database, task.client_id)
    if task.status not in {"approved", "ready"}:
        raise HTTPException(status_code=409, detail=f"Browser execution requires an approved or ready task; task is {task.status}")
    if task.browser_control_approved_at is None:
        raise HTTPException(
            status_code=409,
            detail="explicit_browser_control_approval_required",
        )
    try:
        ensure_dependencies_verified(database, task)
        job = BrowserWorkerAdapter().submit(
            task_id=task.id, client_id=task.client_id, target_url=request.target_url, instructions=request.instructions
        )
    except BrowserExecutionError as error:
        raise HTTPException(status_code=503 if error.retryable or error.code.endswith("missing") else 422, detail=error.code) from error
    now = datetime.utcnow()
    execution = models.FulfillmentExecution(
        operation_key=request.operation_key, client_id=task.client_id, task_id=task.id, status="running",
        intended_actions=[task.requested_outcome, "Submit scoped instructions to browser worker", "Poll worker result", "Verify evidence separately"],
        simulated_changed_files=[], simulated_test_results=[],
        evidence={
            "executor": "browser_worker",
            "simulated": False,
            "task_id": task.id,
            "client_id": task.client_id,
            "summary": "Approved browser work was submitted to the scoped worker.",
            "external_id": job["job_id"],
            "worker_job_id": job["job_id"],
            "worker_status": job["status"],
            "target_url": request.target_url,
            "browser_control_approval": {
                "approved_by": task.browser_control_approved_by,
                "approved_at": task.browser_control_approved_at.isoformat(),
                "reason": task.browser_control_approval_reason,
            },
        },
        estimated_cost=request.estimated_cost, attempt_count=1, retry_delays_seconds=[], failure_type=None,
        error_message=None, started_at=now, completed_at=now,
    )
    database.add(execution)
    database.flush()
    if task.status == "approved":
        add_status_event(database, task, "approved", "ready", "browser executor", "Dependencies checked")
    add_status_event(database, task, "ready", "running", "browser executor", "Browser worker job submitted")
    task.status = "running"
    database.commit()
    database.refresh(execution)
    return execution_response(execution)


@router.post("/browser-executions/{execution_id}/poll", response_model=schemas.SimulatedExecutionRead)
def poll_browser_execution(execution_id: str, database: Session = Depends(get_database)) -> dict:
    execution = _execution_or_404(database, execution_id)
    if execution.evidence.get("executor") != "browser_worker":
        raise HTTPException(status_code=409, detail="Execution is not a browser-worker execution")
    if execution.status in {"completed", "failed", "blocked"}:
        return execution_response(execution)
    try:
        result = BrowserWorkerAdapter().poll(str(execution.evidence["worker_job_id"]))
    except BrowserExecutionError as error:
        raise HTTPException(status_code=503 if error.retryable else 502, detail=error.code) from error
    execution.evidence = {**execution.evidence, "worker_status": result["status"], "worker_result": result.get("evidence", {})}
    if result["status"] in {"completed", "succeeded"}:
        execution.status = "completed"
        execution.completed_at = datetime.utcnow()
        execution.simulated_test_results = [
            {"name": "browser worker completion", "status": "passed", "simulated": False}
        ]
        execution.evidence = {
            **execution.evidence,
            "summary": "The browser worker reported completion with saved result evidence.",
        }
        task = database.get(models.Task, execution.task_id)
        if task is not None:
            add_status_event(database, task, "running", "completed", "browser executor", "Worker reported completion")
            task.status = "completed"
    elif result["status"] in {"failed", "blocked"}:
        execution.status = result["status"]
        execution.failure_type = "permanent" if result["status"] == "failed" else None
        execution.error_message = str(result.get("error") or "Browser worker reported a failure")[:1000]
    database.commit()
    database.refresh(execution)
    return execution_response(execution)
