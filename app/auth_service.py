"""Single-owner Google OIDC login and opaque server-side sessions."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import os
import secrets
from typing import Optional
from urllib.parse import urlencode

import jwt
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models


GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
OWNER_SCOPES = "openid email profile"
SESSION_COOKIE = "max_owner_session"
STATE_COOKIE = "max_owner_oauth_state"
SESSION_LIFETIME = timedelta(hours=12)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def allowed_owner_emails() -> set[str]:
    return {
        item.strip().casefold()
        for item in os.getenv("MAX_ALLOWED_GOOGLE_EMAILS", "").split(",")
        if item.strip()
    }


def auth_is_configured() -> bool:
    return bool(
        os.getenv("AUTH_SECRET", "").strip()
        and os.getenv("GOOGLE_CLIENT_ID", "").strip()
        and os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        and os.getenv("GOOGLE_REDIRECT_URI", "").strip()
        and allowed_owner_emails()
    )


def auth_is_required() -> bool:
    return os.getenv("MAX_REQUIRE_AUTH", "").strip().casefold() in {"1", "true", "yes"} or bool(
        os.getenv("VERCEL_ENV", "").strip()
    )


def safe_redirect_path(value: Optional[str]) -> str:
    candidate = (value or "/dashboard").strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/dashboard"
    return candidate[:500]


def owner_authorization_url(database: Session, next_path: Optional[str] = None) -> tuple[str, str]:
    if not auth_is_configured():
        raise HTTPException(status_code=503, detail="owner_auth_not_configured")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    database.add(
        models.GoogleOAuthState(
            state_hash=digest(state),
            scopes=OWNER_SCOPES,
            purpose="owner_login",
            nonce_hash=digest(nonce),
            redirect_path=safe_redirect_path(next_path),
            expires_at=datetime.utcnow() + timedelta(minutes=10),
        )
    )
    database.commit()
    query = urlencode(
        {
            "client_id": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
            "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI", "").strip(),
            "response_type": "code",
            "scope": OWNER_SCOPES,
            "state": state,
            "nonce": nonce,
            "prompt": "select_account",
        }
    )
    return f"{GOOGLE_AUTHORIZATION_URL}?{query}", state


def verify_owner_id_token(id_token: str, nonce_hash: str) -> str:
    """Verify Google's signature, audience, expiry, issuer, nonce, and email."""
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    try:
        signing_key = jwt.PyJWKClient(GOOGLE_JWKS_URL).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_id,
            options={"require": ["exp", "iat", "sub", "email", "nonce"]},
        )
    except jwt.PyJWTError as error:
        raise HTTPException(status_code=401, detail="google_id_token_invalid") from error
    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise HTTPException(status_code=401, detail="google_id_token_issuer_invalid")
    if not claims.get("email_verified"):
        raise HTTPException(status_code=403, detail="google_email_not_verified")
    if not secrets.compare_digest(digest(str(claims.get("nonce", ""))), nonce_hash):
        raise HTTPException(status_code=401, detail="google_id_token_nonce_invalid")
    email = str(claims.get("email", "")).casefold()
    if email not in allowed_owner_emails():
        raise HTTPException(status_code=403, detail="google_email_not_allowed")
    return email


def create_owner_session(database: Session, email: str) -> tuple[models.OwnerSession, str]:
    raw_token = secrets.token_urlsafe(48)
    now = datetime.utcnow()
    session = models.OwnerSession(
        token_hash=digest(raw_token),
        email=email.casefold(),
        created_at=now,
        last_seen_at=now,
        expires_at=now + SESSION_LIFETIME,
    )
    database.add(session)
    database.commit()
    database.refresh(session)
    return session, raw_token


def find_owner_session(database: Session, raw_token: str) -> Optional[models.OwnerSession]:
    if not raw_token:
        return None
    session = database.scalar(
        select(models.OwnerSession).where(models.OwnerSession.token_hash == digest(raw_token))
    )
    now = datetime.utcnow()
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        return None
    if session.email.casefold() not in allowed_owner_emails():
        return None
    if session.last_seen_at < now - timedelta(minutes=15):
        session.last_seen_at = now
        database.commit()
    return session


def revoke_owner_session(database: Session, raw_token: str) -> None:
    session = find_owner_session(database, raw_token)
    if session is not None:
        session.revoked_at = datetime.utcnow()
        database.commit()


def secure_cookie(request: Request) -> bool:
    return request.url.scheme == "https" or bool(os.getenv("VERCEL_ENV", "").strip())


def require_owner(request: Request) -> str:
    """Return the authenticated owner identity for sensitive route dependencies.

    The security middleware normally populates ``request.state.owner_email``.
    Keeping this explicit dependency on high-impact routes protects those routes
    even when called through a mounted sub-application or exercised directly in
    tests. Local development remains intentionally usable when authentication is
    not configured; configured/production deployments fail closed.
    """
    email = str(getattr(request.state, "owner_email", "") or "").strip()
    if email:
        return email
    if auth_is_configured() or auth_is_required():
        raise HTTPException(status_code=401, detail="authentication_required")
    request.state.owner_email = "local-development"
    return "local-development"
