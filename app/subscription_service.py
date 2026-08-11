"""Subscription state, entitlement checks, and provider webhook application."""

from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import os

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models


ACTIVE_STATUSES = {"trial", "active"}
VALID_STATUSES = ACTIVE_STATUSES | {"past_due", "paused", "cancelled", "incomplete"}


def billing_enforcement_enabled() -> bool:
    return os.getenv("MAX_BILLING_ENFORCEMENT", "").strip().casefold() in {"1", "true", "yes"}


def get_subscription(database: Session, client_id: str) -> models.ClientSubscription | None:
    return database.scalar(
        select(models.ClientSubscription).where(models.ClientSubscription.client_id == client_id)
    )


def subscription_is_entitled(subscription: models.ClientSubscription | None, now: datetime | None = None) -> bool:
    if subscription is None or subscription.status not in ACTIVE_STATUSES:
        return False
    now = now or datetime.utcnow()
    return subscription.current_period_end is None or subscription.current_period_end > now


def require_fulfillment_entitlement(database: Session, client_id: str) -> None:
    """Fail closed only when paid-mode enforcement is explicitly enabled."""
    if not billing_enforcement_enabled():
        return
    subscription = get_subscription(database, client_id)
    if not subscription_is_entitled(subscription):
        raise HTTPException(
            status_code=402,
            detail={
                "code": "billing_subscription_required",
                "message": "An active subscription is required before fulfillment can start.",
            },
        )


def apply_subscription_event(
    database: Session,
    *,
    event_id: str,
    event_type: str,
    client_id: str,
    provider: str,
    status: str,
    plan: str,
    payload: dict,
    payload_hash: str,
    provider_customer_id: str | None = None,
    provider_subscription_id: str | None = None,
    current_period_start: datetime | None = None,
    current_period_end: datetime | None = None,
    cancel_at_period_end: bool = False,
) -> tuple[models.ClientSubscription, bool]:
    if status not in VALID_STATUSES:
        raise ValueError("subscription_status_invalid")
    existing_event = database.scalar(
        select(models.SubscriptionEvent).where(models.SubscriptionEvent.event_id == event_id)
    )
    if existing_event is not None:
        if not hmac.compare_digest(existing_event.payload_hash, payload_hash):
            raise ValueError("subscription_event_payload_mismatch")
        subscription = get_subscription(database, client_id)
        if subscription is None:
            raise ValueError("subscription_event_replay_missing_subscription")
        return subscription, True

    if database.get(models.Client, client_id) is None:
        raise ValueError("client_not_found")
    subscription = get_subscription(database, client_id)
    if subscription is None:
        subscription = models.ClientSubscription(client_id=client_id)
        database.add(subscription)
        database.flush()
    subscription.status = status
    subscription.plan = plan
    subscription.provider = provider
    subscription.provider_customer_id = provider_customer_id or subscription.provider_customer_id
    subscription.provider_subscription_id = provider_subscription_id or subscription.provider_subscription_id
    subscription.current_period_start = current_period_start
    subscription.current_period_end = current_period_end
    subscription.cancel_at_period_end = cancel_at_period_end
    event = models.SubscriptionEvent(
        event_id=event_id,
        client_id=client_id,
        provider=provider,
        event_type=event_type,
        payload_hash=payload_hash,
        payload=payload,
        processed_at=datetime.utcnow(),
    )
    database.add(event)
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        replay = database.scalar(select(models.SubscriptionEvent).where(models.SubscriptionEvent.event_id == event_id))
        if replay is not None and hmac.compare_digest(replay.payload_hash, payload_hash):
            subscription = get_subscription(database, client_id)
            if subscription is not None:
                return subscription, True
        raise
    database.refresh(subscription)
    return subscription, False


def payload_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def verify_webhook_signature(payload: bytes, signature: str, secret: str | None = None) -> bool:
    configured = (secret if secret is not None else os.getenv("BILLING_WEBHOOK_SECRET", "")).strip()
    provided = signature.strip()
    if not configured or not provided:
        return False
    expected = hmac.new(configured.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)
