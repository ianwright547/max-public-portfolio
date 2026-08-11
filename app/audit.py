"""Append-only audit helpers."""

from typing import Optional

from app import models


def record_event(database, event_type: str, actor: str = "system", client_id: Optional[str] = None, record_type: Optional[str] = None, record_id: Optional[str] = None, details: Optional[dict] = None) -> models.AuditEvent:
    event = models.AuditEvent(
        event_type=event_type,
        actor=actor,
        client_id=client_id,
        record_type=record_type,
        record_id=record_id,
        details=details or {},
    )
    database.add(event)
    database.flush()
    return event
