"""Provider-neutral subscription administration and signed webhook intake."""

import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app import models, schemas
from app.audit import record_event
from app.agency_access_service import require_billing_access
from app.database import get_database
from app.subscription_service import apply_subscription_event, get_subscription, payload_hash, verify_webhook_signature


router = APIRouter(tags=["billing"])


def subscription_response(subscription: models.ClientSubscription) -> dict:
    return {
        "id": subscription.id,
        "client_id": subscription.client_id,
        "status": subscription.status,
        "plan": subscription.plan,
        "provider": subscription.provider,
        "provider_customer_id": subscription.provider_customer_id,
        "provider_subscription_id": subscription.provider_subscription_id,
        "current_period_start": subscription.current_period_start,
        "current_period_end": subscription.current_period_end,
        "cancel_at_period_end": subscription.cancel_at_period_end,
        "metadata_json": subscription.metadata_json,
        "created_at": subscription.created_at,
        "updated_at": subscription.updated_at,
    }


@router.get("/clients/{client_id}/subscription", response_model=schemas.SubscriptionRead)
def read_subscription(
    client_id: str,
    owner_email: str = Depends(require_billing_access),
    database: Session = Depends(get_database),
) -> dict:
    if database.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    subscription = get_subscription(database, client_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return subscription_response(subscription)


@router.put("/clients/{client_id}/subscription", response_model=schemas.SubscriptionRead)
def update_subscription(
    client_id: str,
    request: schemas.SubscriptionUpdate,
    owner_email: str = Depends(require_billing_access),
    database: Session = Depends(get_database),
) -> dict:
    if database.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    if request.current_period_end and request.current_period_start and request.current_period_end <= request.current_period_start:
        raise HTTPException(status_code=422, detail="Subscription period end must be after its start")
    subscription = get_subscription(database, client_id)
    if subscription is None:
        subscription = models.ClientSubscription(client_id=client_id)
        database.add(subscription)
    for field, value in request.model_dump().items():
        setattr(subscription, field, value)
    database.commit()
    database.refresh(subscription)
    record_event(
        database,
        "subscription_updated",
        actor=owner_email,
        client_id=client_id,
        record_type="client_subscription",
        record_id=subscription.id,
        details={"status": subscription.status, "plan": subscription.plan, "provider": subscription.provider},
    )
    return subscription_response(subscription)


@router.post("/billing/webhook")
async def billing_webhook(
    request: Request,
    x_billing_signature: str = Header(default=""),
    database: Session = Depends(get_database),
) -> dict:
    raw_payload = await request.body()
    if not os.getenv("BILLING_WEBHOOK_SECRET", "").strip():
        raise HTTPException(status_code=503, detail="billing_webhook_not_configured")
    if not verify_webhook_signature(raw_payload, x_billing_signature):
        raise HTTPException(status_code=401, detail="billing_webhook_signature_invalid")
    try:
        event = schemas.BillingWebhookEvent.model_validate_json(raw_payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="billing_webhook_payload_invalid") from error
    try:
        subscription, replayed = apply_subscription_event(
            database,
            event_id=event.event_id,
            event_type=event.event_type,
            client_id=event.client_id,
            provider=event.provider,
            status=event.status,
            plan=event.plan,
            payload=event.model_dump(mode="json"),
            payload_hash=payload_hash(raw_payload),
            provider_customer_id=event.provider_customer_id,
            provider_subscription_id=event.provider_subscription_id,
            current_period_start=event.current_period_start,
            current_period_end=event.current_period_end,
            cancel_at_period_end=event.cancel_at_period_end,
        )
    except ValueError as error:
        detail = str(error)
        if detail == "client_not_found":
            raise HTTPException(status_code=404, detail=detail) from error
        if detail == "subscription_event_payload_mismatch":
            raise HTTPException(status_code=409, detail=detail) from error
        raise HTTPException(status_code=422, detail=detail) from error
    return {"ok": True, "event_id": event.event_id, "replayed": replayed, "subscription": subscription_response(subscription)}
