"""Client-scoped GitHub repository references for safe work-packet generation."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_database
from app.github_service import GitHubAppAdapter, GitHubIntegrationError

router = APIRouter(tags=["github repositories"])


@router.post(
    "/clients/{client_id}/github-repository",
    response_model=schemas.GitHubRepositoryConnectionRead,
    status_code=status.HTTP_201_CREATED,
)
def connect_github_repository(
    client_id: str,
    connection: schemas.GitHubRepositoryConnectionCreate,
    database: Session = Depends(get_database),
) -> models.GitHubRepositoryConnection:
    """Save one explicitly assigned repository. This does not call GitHub yet."""
    if database.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    existing = database.scalar(
        select(models.GitHubRepositoryConnection).where(
            or_(
                models.GitHubRepositoryConnection.client_id == client_id,
                models.GitHubRepositoryConnection.repository_url == connection.repository_url,
            )
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Client or GitHub repository is already linked")
    record = models.GitHubRepositoryConnection(client_id=client_id, **connection.model_dump())
    database.add(record)
    database.commit()
    database.refresh(record)
    return record


@router.get(
    "/clients/{client_id}/github-repository",
    response_model=schemas.GitHubRepositoryConnectionRead,
)
def read_github_repository(
    client_id: str, database: Session = Depends(get_database)
) -> models.GitHubRepositoryConnection:
    if database.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    record = database.scalar(
        select(models.GitHubRepositoryConnection).where(
            models.GitHubRepositoryConnection.client_id == client_id
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="GitHub repository connection not found")
    return record


@router.post(
    "/clients/{client_id}/github-repository/verify",
    response_model=schemas.GitHubRepositoryVerificationRead,
)
def verify_github_repository(
    client_id: str, database: Session = Depends(get_database)
) -> dict:
    """Read GitHub metadata and record any owner, repo, URL, or branch mismatch."""
    record = read_github_repository(client_id, database)
    checked_at = datetime.utcnow()
    issues: list[str] = []
    try:
        repository = GitHubAppAdapter().get_repository(record.owner, record.repository_name)
        expected_url = record.repository_url.rstrip("/").lower()
        actual_url = repository.html_url.rstrip("/").lower()
        if repository.owner.lower() != record.owner.lower():
            issues.append("github_owner_mismatch")
        if repository.name.lower() != record.repository_name.lower():
            issues.append("github_repository_name_mismatch")
        if actual_url != expected_url:
            issues.append("github_repository_url_mismatch")
        if repository.default_branch != record.default_branch:
            issues.append("github_default_branch_mismatch")
        record.connection_status = "connected" if not issues else "mismatch"
        if not issues:
            record.last_verified_at = checked_at
    except GitHubIntegrationError as error:
        record.connection_status = "error"
        issues.append(error.code)
    record.last_checked_at = checked_at
    database.commit()
    return {
        "client_id": client_id,
        "repository_url": record.repository_url,
        "connection_status": record.connection_status,
        "last_checked_at": checked_at,
        "issues": issues,
    }
