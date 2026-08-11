"""Execute approved packet-scoped website changes through GitHub."""

from datetime import datetime
import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_database
from app.routes.fulfillment import execution_response
from app.routes.tasks import add_status_event, ensure_dependencies_verified, require_active_client, require_task
from app.website_execution import (
    WebsiteExecutionError,
    audit_generated_website_files,
    commit_website_files,
    ensure_site_artifacts,
    revert_website_commit,
)
from app.vercel_service import VercelAdapter, VercelIntegrationError
from app.subscription_service import require_fulfillment_entitlement
from app.client_provider_verification import ProviderVerificationBlocked, require_provider_health


router = APIRouter(tags=["website execution"])


def _website_execution_or_404(database: Session, execution_id: str) -> models.FulfillmentExecution:
    execution = database.get(models.FulfillmentExecution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


@router.post("/tasks/{task_id}/website-executions", response_model=schemas.SimulatedExecutionRead, status_code=status.HTTP_201_CREATED)
def execute_website_task(task_id: str, request: schemas.WebsiteExecutionCreate, database: Session = Depends(get_database)) -> dict:
    existing = database.scalar(select(models.FulfillmentExecution).where(models.FulfillmentExecution.operation_key == request.operation_key))
    if existing is not None:
        if existing.task_id != task_id:
            raise HTTPException(status_code=409, detail="Operation key already belongs to another task")
        return execution_response(existing, True)
    task = require_task(database, task_id)
    require_active_client(database, task.client_id)
    require_fulfillment_entitlement(database, task.client_id)
    if task.status not in {"approved", "ready"}:
        raise HTTPException(status_code=409, detail=f"Website execution requires an approved or ready task; task is {task.status}")
    packet = database.get(models.CodexWorkPacket, request.packet_id)
    if packet is None or packet.task_id != task.id or packet.client_id != task.client_id:
        raise HTTPException(status_code=409, detail="Work packet does not match this client task")
    if packet.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=409, detail="Work packet has expired")
    if packet.publishing_allowed and task.status != "ready":
        raise HTTPException(status_code=409, detail="Publishing requires a ready task")
    try:
        require_provider_health(database, task.client_id, {"website", "github"})
    except ProviderVerificationBlocked as error:
        database.commit()
        raise HTTPException(
            status_code=503,
            detail={"code": "provider_verification_required", "providers": error.codes},
        ) from error
    submitted_files = ensure_site_artifacts(
        [item.model_dump() for item in request.files],
        packet.domain,
    )
    if task.status == "approved":
        ensure_dependencies_verified(database, task)
        add_status_event(database, task, "approved", "ready", "website executor", "Dependencies checked")
        task.status = "ready"
    try:
        result = commit_website_files(
            owner=packet.repository_owner,
            repository=packet.repository_name,
            branch=packet.branch,
            files=submitted_files,
            allowed_paths=packet.allowed_paths,
            prohibited_paths=packet.prohibited_paths,
            commit_message=request.commit_message,
        )
    except WebsiteExecutionError as error:
        database.rollback()
        code = str(error)
        raise HTTPException(status_code=422 if code.startswith("website_") else 503, detail=code) from error
    deployment: dict[str, object] = {"status": "pending_linked_vercel_deployment"}
    if os.getenv("MAX_ENABLE_EXTERNAL_WRITES", "").strip().casefold() in {"1", "true", "yes"}:
        try:
            deployment = {"status": "queued", **VercelAdapter().trigger_git_deployment(
                packet.vercel_project_id, packet.repository_owner, packet.repository_name, packet.branch
            )}
        except VercelIntegrationError as error:
            deployment = {"status": "failed", "error_code": error.code}
    now = datetime.utcnow()
    execution = models.FulfillmentExecution(
        operation_key=request.operation_key,
        client_id=task.client_id,
        task_id=task.id,
        status="completed",
        intended_actions=[task.requested_outcome, "Validate packet scope", "Commit approved website files", "Wait for linked Vercel deployment"],
        simulated_changed_files=result["changed_paths"],
        simulated_test_results=[{"name": "packet scope and secret scan", "status": "passed", "simulated": False}],
        evidence={
            "executor": "github_app",
            "simulated": False,
            "task_id": task.id,
            "client_id": task.client_id,
            "summary": "Approved packet-scoped website files were committed through GitHub.",
            "commit_shas": result["commit_shas"],
            "branch": result["branch"],
            "vercel_project_id": packet.vercel_project_id,
            "deployment": deployment,
            "website_artifact_audit": audit_generated_website_files(
                submitted_files
            ),
        },
        estimated_cost=0.0,
        attempt_count=1,
        retry_delays_seconds=[],
        failure_type=None,
        error_message=None,
        started_at=now,
        completed_at=now,
    )
    database.add(execution)
    database.flush()
    add_status_event(database, task, "ready", "completed", "website executor", "Approved files committed; external verification remains separate")
    task.status = "completed"
    database.commit()
    database.refresh(execution)
    return execution_response(execution)


@router.post("/website-executions/{execution_id}/deployment-poll", response_model=schemas.SimulatedExecutionRead)
def poll_website_deployment(execution_id: str, database: Session = Depends(get_database)) -> dict:
    """Refresh linked Vercel state; deployment failure becomes an explicit blocker."""
    execution = _website_execution_or_404(database, execution_id)
    if execution.evidence.get("executor") != "github_app":
        raise HTTPException(status_code=409, detail="Execution is not a GitHub website execution")
    deployment = execution.evidence.get("deployment") or {}
    deployment_id = deployment.get("deployment_id")
    if not deployment_id:
        raise HTTPException(status_code=409, detail="No linked Vercel deployment exists for this execution")
    if deployment.get("status") in {"ready", "canceled"}:
        return execution_response(execution)
    if deployment.get("status") == "failed":
        execution.status = "blocked"
        execution.failure_type = "external_failure"
        execution.error_message = str(deployment.get("error_code") or "Vercel deployment failed")[:1000]
        task = database.get(models.Task, execution.task_id)
        if task is not None and task.status == "completed":
            add_status_event(database, task, "completed", "blocked", "vercel deployment poll", "Linked deployment failed")
            task.status = "blocked"
        database.commit()
        database.refresh(execution)
        return execution_response(execution)
    try:
        state = VercelAdapter().get_deployment(str(deployment_id))
    except VercelIntegrationError as error:
        raise HTTPException(status_code=503 if error.retryable else 502, detail=error.code) from error
    ready_state = str(state.get("ready_state") or "unknown").casefold()
    if ready_state in {"ready", "completed"}:
        status_value = "ready"
    elif ready_state in {"error", "failed"}:
        status_value = "failed"
    elif ready_state in {"canceled", "cancelled"}:
        status_value = "canceled"
    else:
        status_value = "pending"
    execution.evidence = {
        **execution.evidence,
        "deployment": {**deployment, **state, "status": status_value, "deployment_verified": status_value == "ready"},
    }
    if status_value in {"failed", "canceled"}:
        execution.error_message = str(state.get("error_code") or "Vercel deployment did not become ready")[:1000]
        execution.failure_type = "external_failure"
        task = database.get(models.Task, execution.task_id)
        if task is not None and task.status == "completed":
            add_status_event(database, task, "completed", "blocked", "vercel deployment poll", "Linked deployment failed or was canceled")
            task.status = "blocked"
        execution.status = "blocked"
    database.commit()
    database.refresh(execution)
    return execution_response(execution)


@router.post("/website-executions/{execution_id}/rollback", response_model=schemas.SimulatedExecutionRead)
def rollback_website_execution(
    execution_id: str,
    request: schemas.WebsiteRollbackCreate,
    database: Session = Depends(get_database),
) -> dict:
    """Create one scoped GitHub revert and require fresh verification afterward."""
    execution = _website_execution_or_404(database, execution_id)
    if execution.evidence.get("executor") != "github_app":
        raise HTTPException(status_code=409, detail="Execution is not a GitHub website execution")
    rollback = execution.evidence.get("rollback") or {}
    if rollback.get("operation_key") == request.operation_key:
        return execution_response(execution, True)
    if rollback.get("status") == "completed":
        raise HTTPException(status_code=409, detail="Execution has already been rolled back")
    commit_shas = execution.evidence.get("commit_shas") or []
    if not commit_shas:
        raise HTTPException(status_code=409, detail="Execution has no recorded commit to roll back")
    task = database.get(models.Task, execution.task_id)
    packet = database.scalar(select(models.CodexWorkPacket).where(models.CodexWorkPacket.task_id == execution.task_id))
    if task is None or packet is None:
        raise HTTPException(status_code=409, detail="Original task packet is unavailable")
    try:
        result = revert_website_commit(
            owner=packet.repository_owner,
            repository=packet.repository_name,
            branch=str(execution.evidence.get("branch") or packet.branch),
            commit_sha=str(commit_shas[-1]),
        )
    except WebsiteExecutionError as error:
        execution.evidence = {
            **execution.evidence,
            "rollback": {"status": "failed", "operation_key": request.operation_key, "reason": request.reason, "error_code": str(error)},
        }
        database.commit()
        raise HTTPException(status_code=503 if str(error).endswith("temporarily_unavailable") else 422, detail=str(error)) from error
    execution.evidence = {
        **execution.evidence,
        "rollback": {
            "status": "completed",
            "operation_key": request.operation_key,
            "reason": request.reason,
            **result,
        },
    }
    if task.status in {"completed", "verified"}:
        add_status_event(database, task, task.status, "blocked", "website rollback", "Rollback completed; fresh verification is required")
        task.status = "blocked"
    record = execution_response(execution)
    database.commit()
    database.refresh(execution)
    return record
