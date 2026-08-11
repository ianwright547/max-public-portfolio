"""Intake endpoints belong here.

Keep intake-specific HTTP behavior separate from client behavior.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_database

router = APIRouter(tags=["intakes"])


@router.post(
    "/clients/{client_id}/intakes",
    response_model=schemas.IntakeRead,
    status_code=status.HTTP_201_CREATED,
)
def submit_intake(
    client_id: str,
    intake: schemas.IntakeCreate,
    database: Session = Depends(get_database),
) -> models.Intake:
    """Save one onboarding form for an existing client."""
    if database.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")

    record = models.Intake(client_id=client_id, submitted_at=datetime.utcnow(), **intake.model_dump())
    database.add(record)
    database.flush()
    from app.onboarding_automation import queue_onboarding_run

    queue_onboarding_run(database, client_id, record.id)
    database.commit()
    database.refresh(record)
    return record


@router.get("/intakes/{intake_id}", response_model=schemas.IntakeRead)
def read_intake(
    intake_id: str,
    database: Session = Depends(get_database),
) -> models.Intake:
    """Return one saved onboarding form by ID."""
    record = database.get(models.Intake, intake_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Intake not found")
    return record
