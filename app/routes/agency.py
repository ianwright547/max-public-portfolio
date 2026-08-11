"""Agency member directory and role administration."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.agency_access_service import require_capability
from app.database import get_database


router = APIRouter(prefix="/agency", tags=["agency access"])


def _member_response(member: models.AgencyMember) -> dict:
    return {
        "id": member.id,
        "email": member.email,
        "display_name": member.display_name,
        "role": member.role,
        "slack_user_id": member.slack_user_id,
        "active": member.active,
        "created_at": member.created_at,
        "updated_at": member.updated_at,
    }


def _ensure_owner_survives(database: Session, member: models.AgencyMember, *, new_role: str | None = None, active: bool | None = None) -> None:
    becomes_owner = new_role if new_role is not None else member.role
    remains_active = active if active is not None else member.active
    if becomes_owner == "owner" and remains_active:
        return
    count = database.scalar(
        select(func.count()).select_from(models.AgencyMember).where(
            models.AgencyMember.role == "owner",
            models.AgencyMember.active.is_(True),
            models.AgencyMember.id != member.id,
        )
    ) or 0
    if member.role == "owner" and member.active and count == 0 and (becomes_owner != "owner" or not remains_active):
        raise HTTPException(status_code=409, detail="agency_must_retain_one_active_owner")


@router.get("/members", response_model=list[schemas.AgencyMemberRead])
def list_members(request: Request, database: Session = Depends(get_database)) -> list[dict]:
    require_capability(request, database, "manage_members")
    members = list(database.scalars(select(models.AgencyMember).order_by(models.AgencyMember.email)))
    return [_member_response(member) for member in members]


@router.post("/members", response_model=schemas.AgencyMemberRead, status_code=status.HTTP_201_CREATED)
def create_member(
    payload: schemas.AgencyMemberCreate,
    request: Request,
    database: Session = Depends(get_database),
) -> dict:
    actor = require_capability(request, database, "manage_members")
    email = str(payload.email).casefold()
    if database.scalar(select(models.AgencyMember).where(models.AgencyMember.email == email)) is not None:
        raise HTTPException(status_code=409, detail="agency_member_email_exists")
    if payload.slack_user_id and database.scalar(
        select(models.AgencyMember).where(models.AgencyMember.slack_user_id == payload.slack_user_id)
    ) is not None:
        raise HTTPException(status_code=409, detail="agency_member_slack_user_exists")
    member = models.AgencyMember(
        email=email,
        display_name=payload.display_name,
        role=payload.role,
        slack_user_id=payload.slack_user_id,
        active=True,
    )
    database.add(member)
    database.flush()
    database.add(
        models.AuditEvent(
            event_type="agency_member_created",
            actor=actor,
            record_type="agency_member",
            record_id=member.id,
            details={"role": member.role, "slack_user_id_mapped": bool(member.slack_user_id)},
        )
    )
    database.commit()
    database.refresh(member)
    return _member_response(member)


@router.patch("/members/{member_id}", response_model=schemas.AgencyMemberRead)
def update_member(
    member_id: str,
    payload: schemas.AgencyMemberUpdate,
    request: Request,
    database: Session = Depends(get_database),
) -> dict:
    actor = require_capability(request, database, "manage_members")
    member = database.get(models.AgencyMember, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="agency_member_not_found")
    if payload.slack_user_id and payload.slack_user_id != member.slack_user_id:
        duplicate = database.scalar(
            select(models.AgencyMember).where(
                models.AgencyMember.slack_user_id == payload.slack_user_id,
                models.AgencyMember.id != member.id,
            )
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="agency_member_slack_user_exists")
    _ensure_owner_survives(database, member, new_role=payload.role, active=payload.active)
    changes = payload.model_dump(exclude_unset=True)
    if "slack_user_id" in changes and changes["slack_user_id"] == "":
        changes["slack_user_id"] = None
    for key, value in changes.items():
        setattr(member, key, value)
    member.updated_at = datetime.utcnow()
    database.add(
        models.AuditEvent(
            event_type="agency_member_updated",
            actor=actor,
            record_type="agency_member",
            record_id=member.id,
            details={"changed_fields": sorted(changes)},
        )
    )
    database.commit()
    database.refresh(member)
    return _member_response(member)
