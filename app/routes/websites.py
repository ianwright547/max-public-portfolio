"""Verified client-to-hosting-project connections."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_database
from app.vercel_service import VercelAdapter, VercelIntegrationError

router = APIRouter(tags=["websites"])


@router.post(
    "/clients/{client_id}/website-connection",
    response_model=schemas.WebsiteConnectionRead,
    status_code=status.HTTP_201_CREATED,
)
def connect_website(
    client_id: str,
    connection: schemas.WebsiteConnectionCreate,
    database: Session = Depends(get_database),
) -> models.WebsiteConnection:
    """Link verified Vercel metadata without deploying or changing the website."""
    if database.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")

    existing = database.scalar(
        select(models.WebsiteConnection).where(
            or_(
                models.WebsiteConnection.client_id == client_id,
                models.WebsiteConnection.external_project_id == connection.external_project_id,
                models.WebsiteConnection.project_name == connection.project_name,
            )
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Client or Vercel project is already linked")

    record = models.WebsiteConnection(client_id=client_id, **connection.model_dump())
    database.add(record)
    database.commit()
    database.refresh(record)
    return record


@router.get(
    "/clients/{client_id}/website-connection",
    response_model=schemas.WebsiteConnectionRead,
)
def read_website_connection(
    client_id: str,
    database: Session = Depends(get_database),
) -> models.WebsiteConnection:
    if database.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    record = database.scalar(
        select(models.WebsiteConnection).where(models.WebsiteConnection.client_id == client_id)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Website connection not found")
    return record


@router.post(
    "/website-connections/sync",
    response_model=list[schemas.WebsiteConnectionSyncRead],
)
def sync_website_connections(database: Session = Depends(get_database)) -> list[dict]:
    """Verify imported Vercel projects without deploying or changing them."""
    try:
        adapter = VercelAdapter()
    except VercelIntegrationError as error:
        raise HTTPException(status_code=503, detail=error.code) from error

    results: list[dict] = []
    connections = list(database.scalars(select(models.WebsiteConnection)))
    for connection in connections:
        integration = database.scalar(
            select(models.IntegrationConnection).where(
                models.IntegrationConnection.client_id == connection.client_id,
                models.IntegrationConnection.integration_name == "Vercel",
            )
        )
        if integration is None:
            integration = models.IntegrationConnection(
                client_id=connection.client_id,
                integration_name="Vercel",
                connection_status="unknown",
                data_source_type="live_api",
                issues=[],
            )
            database.add(integration)
        checked_at = datetime.utcnow()
        issues: list[str] = []
        try:
            project = adapter.get_project(connection.external_project_id)
            if project.project_id != connection.external_project_id:
                issues.append("vercel_project_id_mismatch")
            if project.project_name and project.project_name != connection.project_name:
                issues.append("vercel_project_name_mismatch")
            integration.connection_status = "connected" if not issues else "mismatch"
        except VercelIntegrationError as error:
            integration.connection_status = "error"
            issues.append(error.code)
        integration.last_checked_at = checked_at
        integration.issues = issues
        results.append({
            "client_id": connection.client_id,
            "project_id": connection.external_project_id,
            "connection_status": integration.connection_status,
            "last_checked_at": checked_at,
            "issues": issues,
        })
    database.commit()
    return results
