"""Approval-gated Google Business Profile connection and post workflow."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.audit import record_event
from app.database import get_database
from app.google_business_profile_service import GoogleBusinessProfileAdapter, GoogleBusinessProfileIntegrationError
from app.notification_service import deliver_notification, NotificationEvent
from app.subscription_service import require_fulfillment_entitlement
from app.client_provider_verification import ProviderVerificationBlocked, require_provider_health


router = APIRouter(tags=["google business profile"])


def _record_inspection_status(
    database: Session,
    client_id: str,
    status_value: str,
    issues: list[str],
    checked_at: datetime,
) -> None:
    integration = database.scalar(
        select(models.IntegrationConnection).where(
            models.IntegrationConnection.client_id == client_id,
            models.IntegrationConnection.integration_name == "Google Business Profile",
            models.IntegrationConnection.data_source_type == "live_api",
        )
    )
    if integration is None:
        integration = models.IntegrationConnection(
            client_id=client_id,
            integration_name="Google Business Profile",
            connection_status=status_value,
            data_source_type="live_api",
            issues=issues,
        )
        database.add(integration)
    integration.connection_status = status_value
    integration.last_checked_at = checked_at
    integration.issues = issues


@router.get("/clients/{client_id}/google-business-profile/inspection")
def inspect_profile(client_id: str, database: Session = Depends(get_database)) -> dict:
    """Return a live, aggregate-only GBP inspection for the mapped client location."""
    connection = database.scalar(
        select(models.GoogleBusinessProfileConnection).where(
            models.GoogleBusinessProfileConnection.client_id == client_id
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Google Business Profile connection not found")
    checked_at = datetime.utcnow()
    try:
        inspection = GoogleBusinessProfileAdapter().inspect_location(
            connection.account_id, connection.location_id
        )
    except GoogleBusinessProfileIntegrationError as error:
        _record_inspection_status(database, client_id, "error", [error.code], checked_at)
        connection.last_checked_at = checked_at
        database.commit()
        status_code = 503 if error.retryable else 502
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    connection.last_checked_at = checked_at
    _record_inspection_status(database, client_id, "connected", [], checked_at)
    database.commit()
    return {"client_id": client_id, "connection_id": connection.id, "inspection": inspection.as_dict()}


@router.post("/clients/{client_id}/google-business-profile", response_model=schemas.GoogleBusinessProfileConnectionRead, status_code=status.HTTP_201_CREATED)
def connect_profile(client_id: str, request: schemas.GoogleBusinessProfileConnectionCreate, database: Session = Depends(get_database)) -> models.GoogleBusinessProfileConnection:
    if database.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    existing = database.scalar(
        select(models.GoogleBusinessProfileConnection).where(
            (models.GoogleBusinessProfileConnection.client_id == client_id)
            | ((models.GoogleBusinessProfileConnection.account_id == request.account_id) & (models.GoogleBusinessProfileConnection.location_id == request.location_id))
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Google Business Profile location is already linked")
    record = models.GoogleBusinessProfileConnection(client_id=client_id, **request.model_dump())
    database.add(record)
    database.commit()
    database.refresh(record)
    return record


@router.get("/clients/{client_id}/google-business-profile", response_model=schemas.GoogleBusinessProfileConnectionRead)
def read_profile(client_id: str, database: Session = Depends(get_database)) -> models.GoogleBusinessProfileConnection:
    record = database.scalar(select(models.GoogleBusinessProfileConnection).where(models.GoogleBusinessProfileConnection.client_id == client_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Google Business Profile connection not found")
    return record


@router.post("/clients/{client_id}/google-business-profile/posts", response_model=schemas.GoogleBusinessProfilePostRead, status_code=status.HTTP_201_CREATED)
def create_post(client_id: str, request: schemas.GoogleBusinessProfilePostCreate, database: Session = Depends(get_database)) -> models.GoogleBusinessProfilePost:
    connection = read_profile(client_id, database)
    require_fulfillment_entitlement(database, client_id)
    existing = database.scalar(select(models.GoogleBusinessProfilePost).where(models.GoogleBusinessProfilePost.operation_key == request.operation_key))
    if existing is not None:
        if existing.client_id != client_id:
            raise HTTPException(status_code=409, detail="Operation key belongs to another client")
        return existing
    post = models.GoogleBusinessProfilePost(client_id=client_id, connection_id=connection.id, **request.model_dump())
    database.add(post)
    database.flush()
    deliver_notification(database, NotificationEvent(
        event_key=f"approval-required:gbp-post:{post.id}", client_id=client_id,
        category="approval_required", importance="medium",
        explanation="A Google Business Profile post draft is ready for owner approval.",
        requested_action="Review and approve the post before publishing.",
        related_record_type="google_business_profile_post", related_record_id=post.id,
    ))
    database.commit()
    database.refresh(post)
    return post


@router.post("/google-business-profile/posts/{post_id}/approval", response_model=schemas.GoogleBusinessProfilePostRead)
def approve_post(post_id: str, request: schemas.GoogleBusinessProfilePostApproval, database: Session = Depends(get_database)) -> models.GoogleBusinessProfilePost:
    post = database.get(models.GoogleBusinessProfilePost, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Google Business Profile post not found")
    if post.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft posts can be approved")
    post.status = "approved"
    post.approved_by = request.approved_by
    post.approved_at = datetime.utcnow()
    record_event(
        database,
        "gbp_post_approved",
        actor=request.approved_by,
        client_id=post.client_id,
        record_type="google_business_profile_post",
        record_id=post.id,
        details={"connection_id": post.connection_id},
    )
    database.commit()
    database.refresh(post)
    return post


@router.post("/google-business-profile/posts/{post_id}/publish", response_model=schemas.GoogleBusinessProfilePostRead)
def publish_post(post_id: str, database: Session = Depends(get_database)) -> models.GoogleBusinessProfilePost:
    post = database.get(models.GoogleBusinessProfilePost, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Google Business Profile post not found")
    if post.status == "published":
        return post
    if post.status == "publishing":
        raise HTTPException(status_code=409, detail="GBP post publication is already in progress")
    if post.status != "approved":
        raise HTTPException(status_code=409, detail="Owner approval is required before publishing")
    require_fulfillment_entitlement(database, post.client_id)
    connection = database.get(models.GoogleBusinessProfileConnection, post.connection_id)
    if connection is None:
        post.status = "failed"
        post.error_code = "gbp_connection_missing"
        database.commit()
        raise HTTPException(status_code=409, detail="GBP connection is no longer available")
    try:
        require_provider_health(database, post.client_id, {"google_business_profile"})
    except ProviderVerificationBlocked as error:
        database.commit()
        raise HTTPException(
            status_code=503,
            detail={"code": "provider_verification_required", "providers": error.codes},
        ) from error
    post.status = "publishing"
    record_event(
        database,
        "gbp_post_publish_started",
        actor="system",
        client_id=post.client_id,
        record_type="google_business_profile_post",
        record_id=post.id,
        details={"location_id": connection.location_id},
    )
    # Commit the in-flight marker before the provider call so concurrent
    # requests cannot publish the same approved draft twice.
    database.commit()
    try:
        result = GoogleBusinessProfileAdapter().publish_post(connection.location_id, post.summary, post.call_to_action_url)
    except GoogleBusinessProfileIntegrationError as error:
        post.status = "failed"
        post.error_code = error.code
        record_event(
            database,
            "gbp_post_publish_failed",
            actor="system",
            client_id=post.client_id,
            record_type="google_business_profile_post",
            record_id=post.id,
            details={"error_code": error.code},
        )
        database.commit()
        raise HTTPException(status_code=503 if error.retryable else 502, detail=error.code) from error
    post.status = "published"
    post.external_post_id = result.post_id
    post.published_at = datetime.utcnow()
    record_event(
        database,
        "gbp_post_published",
        actor="system",
        client_id=post.client_id,
        record_type="google_business_profile_post",
        record_id=post.id,
        details={"external_post_id": result.post_id, "location_id": connection.location_id},
    )
    database.commit()
    database.refresh(post)
    return post
