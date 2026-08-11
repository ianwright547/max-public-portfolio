"""Role and identity checks for agency team members."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.auth_service import allowed_owner_emails, auth_is_configured, auth_is_required
from app.database import get_database


ROLE_CAPABILITIES = {
    "owner": {"read", "client_operations", "fulfillment", "reporting", "billing", "manage_members"},
    "admin": {"read", "client_operations", "fulfillment", "reporting", "billing"},
    "operator": {"read", "client_operations", "fulfillment", "reporting"},
    "viewer": {"read", "reporting"},
}


def member_for_email(database: Session, email: str) -> Optional[models.AgencyMember]:
    return database.scalar(
        select(models.AgencyMember).where(
            models.AgencyMember.email == email.casefold(),
            models.AgencyMember.active.is_(True),
        )
    )


def role_for_email(database: Session, email: str) -> str:
    member = member_for_email(database, email)
    if member is not None:
        return member.role
    # Existing deployments have only the configured owner allowlist. Treating
    # those identities as owners keeps the migration backward-compatible while
    # the agency member directory is populated.
    if email.casefold() in allowed_owner_emails():
        return "owner"
    return "viewer"


def has_capability(role: str, capability: str) -> bool:
    return capability in ROLE_CAPABILITIES.get(role, set())


def require_capability(request: Request, database: Session, capability: str) -> str:
    email = str(getattr(request.state, "owner_email", "") or "").strip().casefold()
    if not email:
        if auth_is_configured() or auth_is_required():
            raise HTTPException(status_code=401, detail="authentication_required")
        email = "local-development"
        request.state.owner_email = email
    role = "owner" if email == "local-development" else role_for_email(database, email)
    if not has_capability(role, capability):
        raise HTTPException(status_code=403, detail=f"agency_role_{capability}_required")
    request.state.agency_role = role
    return email


def slack_member_for_user(database: Session, slack_user_id: str) -> Optional[models.AgencyMember]:
    return database.scalar(
        select(models.AgencyMember).where(
            models.AgencyMember.slack_user_id == slack_user_id,
            models.AgencyMember.active.is_(True),
        )
    )


def slack_user_has_capability(database: Session, slack_user_id: str, capability: str) -> bool:
    member = slack_member_for_user(database, slack_user_id)
    return member is not None and has_capability(member.role, capability)


def require_reporting_access(
    request: Request, database: Session = Depends(get_database)
) -> str:
    return require_capability(request, database, "reporting")


def require_billing_access(
    request: Request, database: Session = Depends(get_database)
) -> str:
    return require_capability(request, database, "billing")


def require_fulfillment_access(
    request: Request, database: Session = Depends(get_database)
) -> str:
    return require_capability(request, database, "fulfillment")


def require_client_operations_access(
    request: Request, database: Session = Depends(get_database)
) -> str:
    return require_capability(request, database, "client_operations")
