"""Client endpoints belong here.

Put client-specific HTTP behavior in this module.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, schemas
from app import slack_service
from app.audit import record_event
from app.client_lifecycle_service import disable_client_jobs
from app.database import get_database
from app.readiness_service import build_client_launch_readiness
from app.client_provider_verification import verify_client_providers

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("/{client_id}/launch-readiness")
def client_launch_readiness(
    client_id: str,
    database: Session = Depends(get_database),
) -> dict:
    """Return the client-specific gate for reports, fulfillment, and recurring work."""
    try:
        return build_client_launch_readiness(database, client_id)
    except ValueError as error:
        if str(error) == "client_not_found":
            raise HTTPException(status_code=404, detail="Client not found") from error
        raise


@router.post("/{client_id}/provider-verification")
def client_provider_verification(
    client_id: str,
    database: Session = Depends(get_database),
) -> dict:
    """Run bounded read-only probes against this client's saved providers."""
    try:
        result = verify_client_providers(database, client_id)
    except ValueError as error:
        if str(error) == "client_not_found":
            raise HTTPException(status_code=404, detail="Client not found") from error
        raise
    database.commit()
    return result


@router.post("", response_model=schemas.ClientRead, status_code=status.HTTP_201_CREATED)
def create_client(
    client: schemas.ClientCreate,
    database: Session = Depends(get_database),
) -> models.Client:
    """Create one client record."""
    existing_client = database.scalar(
        select(models.Client).where(func.lower(models.Client.business_name) == client.business_name.lower())
    )
    if existing_client is not None:
        raise HTTPException(status_code=409, detail="Client already exists")

    record = models.Client(**client.model_dump())
    database.add(record)
    database.commit()
    database.refresh(record)
    return record


@router.get("", response_model=list[schemas.ClientRead])
def list_clients(
    include_archived: bool = Query(False),
    database: Session = Depends(get_database),
) -> list[models.Client]:
    """Return active clients by default; history can explicitly include archived clients."""
    query = select(models.Client)
    if not include_archived:
        query = query.where(models.Client.archived_at.is_(None))
    return list(database.scalars(query.order_by(models.Client.business_name)))


@router.patch("/{client_id}", response_model=schemas.ClientRead)
def update_client(
    client_id: str,
    client: schemas.ClientUpdate,
    database: Session = Depends(get_database),
) -> models.Client:
    """Update basic information without changing historical client records."""
    record = database.get(models.Client, client_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Client not found")
    changes = client.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field is required")
    if "business_name" in changes:
        duplicate = database.scalar(
            select(models.Client).where(
                func.lower(models.Client.business_name) == changes["business_name"].lower(),
                models.Client.id != client_id,
            )
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Client already exists")
    for field, value in changes.items():
        setattr(record, field, value)
    database.commit()
    database.refresh(record)
    return record


@router.post("/{client_id}/archive", response_model=schemas.ClientRead)
def archive_client(
    client_id: str,
    database: Session = Depends(get_database),
) -> models.Client:
    """Archive a client while retaining every related record."""
    record = database.get(models.Client, client_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Client not found")
    if record.archived_at is None:
        record.archived_at = datetime.now(timezone.utc).replace(tzinfo=None)
        record.status = "archived"
    disable_client_jobs(database, record.id)
    database.commit()
    database.refresh(record)
    return record


@router.delete("/{client_id}", response_model=schemas.ClientRead)
def delete_client(
    client_id: str,
    database: Session = Depends(get_database),
) -> models.Client:
    """Remove a client from active operations while preserving audit history.

    Client records are intentionally retained because tasks, reports, costs, and
    approvals are historical evidence. The mapped Slack channel is archived as
    part of the same requested lifecycle operation when Slack is configured.
    """
    record = database.get(models.Client, client_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Client not found")
    if record.archived_at is None:
        record.archived_at = datetime.now(timezone.utc).replace(tzinfo=None)
        record.status = "archived"
    disabled_job_ids = disable_client_jobs(database, record.id)
    connection = database.scalar(
        select(models.SlackChannelConnection).where(
            models.SlackChannelConnection.client_id == record.id
        )
    )
    if connection is not None and connection.connection_status in {"connected", "connected_public"}:
        try:
            slack_service.get_slack_adapter().archive_channel(connection.channel_id)
            connection.connection_status = "archived"
            connection.last_error = None
        except slack_service.SlackIntegrationError as error:
            connection.connection_status = "archive_pending"
            connection.last_error = error.code
    record_event(
        database,
        "client_removed_from_active_operations",
        actor="owner",
        client_id=record.id,
        record_type="client",
        record_id=record.id,
        details={
            "slack_channel_id": connection.channel_id if connection is not None else None,
            "slack_channel_status": connection.connection_status if connection is not None else "not_connected",
            "history_preserved": True,
            "disabled_scheduled_job_ids": disabled_job_ids,
        },
    )
    database.commit()
    database.refresh(record)
    return record


@router.get("/{client_id}", response_model=schemas.ClientRead)
def read_client(
    client_id: str,
    database: Session = Depends(get_database),
) -> models.Client:
    """Return one saved client by ID."""
    record = database.get(models.Client, client_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return record
