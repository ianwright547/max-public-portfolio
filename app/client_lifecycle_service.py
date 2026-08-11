"""Shared client lifecycle cleanup rules."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models


def disable_client_jobs(database: Session, client_id: str) -> list[str]:
    """Stop future scheduled work while retaining job history and run records."""
    jobs = list(
        database.scalars(
            select(models.ScheduledJob).where(
                models.ScheduledJob.client_id == client_id,
                models.ScheduledJob.enabled.is_(True),
            )
        )
    )
    for job in jobs:
        job.enabled = False
    return [job.id for job in jobs]
