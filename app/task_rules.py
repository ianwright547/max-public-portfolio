"""Readable Phase 7 task-state rules."""

from fastapi import HTTPException


ACTIVE_TASK_STATUSES = {"proposed", "approved", "blocked", "ready", "running", "completed"}

ALLOWED_TRANSITIONS = {
    "proposed": {"approved", "rejected"},
    "approved": {"blocked", "ready"},
    "blocked": {"ready"},
    "ready": {"running"},
    "running": {"completed", "failed", "blocked"},
    "failed": {"ready"},
    "completed": {"verified", "failed"},
    "rejected": set(),
    "verified": set(),
}


def validate_transition(current_status: str, target_status: str) -> None:
    """Reject skipped, repeated, or terminal task transitions."""
    if target_status not in ALLOWED_TRANSITIONS.get(current_status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Task cannot move from {current_status} to {target_status}",
        )
