"""Prompt compilation endpoints for auditable AI work preparation."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app import schemas
from app.database import get_database
from app.prompt_service import PromptCompilationError, compile_prompt


router = APIRouter(tags=["prompts"])


@router.post(
    "/clients/{client_id}/prompt-artifacts",
    response_model=schemas.PromptArtifactRead,
    status_code=status.HTTP_201_CREATED,
)
def create_prompt_artifact(
    client_id: str,
    request: schemas.PromptCompileRequest,
    database: Session = Depends(get_database),
) -> object:
    try:
        artifact, _reused = compile_prompt(
            database,
            operation_key=request.operation_key,
            client_id=client_id,
            purpose=request.purpose,
            model_role=request.model_role,
            intake_id=request.intake_id,
            task_id=request.task_id,
        )
    except PromptCompilationError as error:
        detail = str(error)
        status_code = 404 if detail in {"client_not_found", "task_not_found_for_client"} else 409
        raise HTTPException(status_code=status_code, detail=detail) from error
    return artifact


@router.get("/prompt-artifacts/{artifact_id}", response_model=schemas.PromptArtifactRead)
def read_prompt_artifact(artifact_id: str, database: Session = Depends(get_database)) -> object:
    artifact = database.get(models.PromptArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Prompt artifact not found")
    return artifact


@router.get("/clients/{client_id}/prompt-artifacts", response_model=list[schemas.PromptArtifactRead])
def list_prompt_artifacts(client_id: str, database: Session = Depends(get_database)) -> list[object]:
    if database.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return list(
        database.scalars(
            select(models.PromptArtifact)
            .where(models.PromptArtifact.client_id == client_id)
            .order_by(models.PromptArtifact.created_at.desc(), models.PromptArtifact.id.desc())
        )
    )
