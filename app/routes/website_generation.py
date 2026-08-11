"""Generate, preview, and execute website files from an approved profile/task."""

from datetime import datetime
import hashlib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_database
from app.routes.website_execution import execute_website_task
from app.subscription_service import require_fulfillment_entitlement
from app.routes.tasks import require_active_client, require_task
from app.website_generation_service import WebsiteGenerationError, generate_files
from app.website_execution import audit_generated_website_files, ensure_site_artifacts, validate_files, WebsiteExecutionError


router = APIRouter(tags=["website generation"])


def preview_response(preview: models.WebsitePreview) -> dict:
    return {
        "id": preview.id,
        "operation_key": preview.operation_key,
        "client_id": preview.client_id,
        "task_id": preview.task_id,
        "packet_id": preview.packet_id,
        "model_role": preview.model_role,
        "files": preview.files,
        "file_manifest": preview.file_manifest,
        "comparison": preview.comparison,
        "technical_audit": preview.technical_audit,
        "status": preview.status,
        "generated_by": preview.generated_by,
        "created_at": preview.created_at,
    }


@router.post("/tasks/{task_id}/website-generation-preview", response_model=schemas.WebsitePreviewRead, status_code=201)
def generate_website_preview(
    task_id: str,
    request: schemas.WebsitePreviewCreate,
    database: Session = Depends(get_database),
) -> dict:
    """Generate and save a reviewable proposal without committing or deploying it."""
    task = require_task(database, task_id)
    require_active_client(database, task.client_id)
    require_fulfillment_entitlement(database, task.client_id)
    if task.status not in {"approved", "ready"}:
        raise HTTPException(status_code=409, detail=f"Website preview requires an approved or ready task; task is {task.status}")
    packet = database.get(models.CodexWorkPacket, request.packet_id)
    if packet is None or packet.task_id != task.id or packet.client_id != task.client_id:
        raise HTTPException(status_code=409, detail="Work packet does not match this client task")
    if packet.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=409, detail="Work packet has expired")
    existing = database.scalar(select(models.WebsitePreview).where(models.WebsitePreview.operation_key == request.operation_key))
    if existing is not None:
        if existing.task_id != task.id or existing.packet_id != packet.id:
            raise HTTPException(status_code=409, detail="Preview operation key belongs to another task")
        return preview_response(existing)
    try:
        files, _artifact_id = generate_files(database, task, model_role=request.model_role)
        files = ensure_site_artifacts(files, packet.domain)
        validate_files(files, packet.allowed_paths, packet.prohibited_paths)
    except WebsiteGenerationError as error:
        database.rollback()
        raise HTTPException(status_code=503 if error.retryable or error.code.endswith("missing") else 422, detail=error.code) from error
    except WebsiteExecutionError as error:
        database.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    manifest = [
        {"path": item["path"], "bytes": len(item["content"].encode()), "sha256": hashlib.sha256(item["content"].encode()).hexdigest()}
        for item in files
    ]
    previous = database.scalar(
        select(models.WebsitePreview)
        .where(
            models.WebsitePreview.packet_id == packet.id,
            models.WebsitePreview.status == "draft",
        )
        .order_by(models.WebsitePreview.created_at.desc(), models.WebsitePreview.id.desc())
    )
    current_hashes = {item["path"]: item["sha256"] for item in manifest}
    previous_hashes = {
        item["path"]: item["sha256"]
        for item in (previous.file_manifest if previous is not None else [])
    }
    comparison = {
        "baseline_preview_id": previous.id if previous is not None else None,
        "added_paths": sorted(set(current_hashes) - set(previous_hashes)),
        "removed_paths": sorted(set(previous_hashes) - set(current_hashes)),
        "changed_paths": sorted(
            path for path in set(current_hashes) & set(previous_hashes)
            if current_hashes[path] != previous_hashes[path]
        ),
        "unchanged_paths": sorted(
            path for path in set(current_hashes) & set(previous_hashes)
            if current_hashes[path] == previous_hashes[path]
        ),
    }
    technical_audit = audit_generated_website_files(files)
    preview = models.WebsitePreview(
        operation_key=request.operation_key,
        client_id=task.client_id,
        task_id=task.id,
        packet_id=packet.id,
        model_role=request.model_role,
        files=files,
        file_manifest=manifest,
        comparison=comparison,
        technical_audit=technical_audit,
        generated_by=request.generated_by,
    )
    database.add(preview)
    database.commit()
    database.refresh(preview)
    return preview_response(preview)


@router.get("/website-previews/{preview_id}", response_model=schemas.WebsitePreviewRead)
def read_website_preview(preview_id: str, database: Session = Depends(get_database)) -> dict:
    preview = database.get(models.WebsitePreview, preview_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Website preview not found")
    return preview_response(preview)


@router.post("/tasks/{task_id}/website-generation", response_model=schemas.SimulatedExecutionRead, status_code=201)
def generate_and_execute_website(task_id: str, request: schemas.WebsiteGenerationCreate, database: Session = Depends(get_database)) -> dict:
    task = require_task(database, task_id)
    require_active_client(database, task.client_id)
    require_fulfillment_entitlement(database, task.client_id)
    if task.status not in {"approved", "ready"}:
        raise HTTPException(status_code=409, detail=f"Website generation requires an approved or ready task; task is {task.status}")
    packet = database.get(models.CodexWorkPacket, request.packet_id)
    if packet is None or packet.task_id != task.id or packet.client_id != task.client_id:
        raise HTTPException(status_code=409, detail="Work packet does not match this client task")
    if packet.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=409, detail="Work packet has expired")
    if packet.publishing_allowed and task.status != "ready":
        raise HTTPException(status_code=409, detail="Publishing requires a ready task")
    try:
        files, _artifact_id = generate_files(database, task, model_role=request.model_role)
    except WebsiteGenerationError as error:
        database.rollback()
        raise HTTPException(status_code=503 if error.retryable or error.code.endswith("missing") else 422, detail=error.code) from error
    execution_request = schemas.WebsiteExecutionCreate(
        operation_key=request.operation_key,
        packet_id=request.packet_id,
        commit_message=request.commit_message,
        files=files,
    )
    return execute_website_task(task_id, execution_request, database)
