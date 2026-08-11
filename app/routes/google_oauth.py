"""Google OAuth setup for Search Console and Business Profile access.

This is an agency-level connection step. It creates a refresh token for the
configured Google account; client/property matching is intentionally handled
when a specific client integration is connected later.
"""

from datetime import datetime, timedelta
from html import escape
import hashlib
import json
import os
import secrets
from typing import Optional, Union
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.audit import record_event
from app.auth_service import (
    SESSION_COOKIE,
    SESSION_LIFETIME,
    STATE_COOKIE,
    create_owner_session,
    secure_cookie,
    verify_owner_id_token,
)
from app.database import get_database


router = APIRouter(tags=["google-oauth"])

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/business.manage",
)
STATE_LIFETIME = timedelta(minutes=10)


def _google_configuration() -> tuple[str, str, str]:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(status_code=503, detail="google_oauth_not_configured")
    return client_id, client_secret, redirect_uri


def _state_digest(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _exchange_code_for_tokens(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    """Exchange an authorization code without logging any token response."""
    payload = urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = UrlRequest(
        GOOGLE_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as error:
        raise HTTPException(status_code=502, detail="google_token_exchange_failed") from error
    try:
        token_data = json.loads(body)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=502, detail="google_token_response_invalid") from error
    if not isinstance(token_data, dict):
        raise HTTPException(status_code=502, detail="google_token_response_invalid")
    return token_data


@router.get("/google/oauth/start", response_class=RedirectResponse)
def start_google_oauth(database: Session = Depends(get_database)) -> RedirectResponse:
    """Start the owner-only setup flow by redirecting to Google's consent page."""
    client_id, _client_secret, redirect_uri = _google_configuration()
    state = secrets.token_urlsafe(32)
    database.add(
        models.GoogleOAuthState(
            state_hash=_state_digest(state),
            scopes=" ".join(GOOGLE_SCOPES),
            purpose="integration_setup",
            expires_at=datetime.utcnow() + STATE_LIFETIME,
        )
    )
    database.commit()
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
            "scope": " ".join(GOOGLE_SCOPES),
            "state": state,
        }
    )
    response = RedirectResponse(url=f"{GOOGLE_AUTHORIZATION_URL}?{query}", status_code=307)
    response.set_cookie(
        "max_google_oauth_state",
        state,
        max_age=int(STATE_LIFETIME.total_seconds()),
        httponly=True,
        secure=redirect_uri.startswith("https://"),
        samesite="lax",
        path="/google/oauth",
    )
    return response


@router.get("/google/oauth/callback", response_model=None)
def complete_google_oauth(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    database: Session = Depends(get_database),
) -> Union[HTMLResponse, RedirectResponse]:
    """Validate the one-time state and show the refresh token exactly once."""
    if error:
        # Do not echo Google's description because it can contain sensitive
        # request details. The owner can restart the flow safely.
        raise HTTPException(status_code=400, detail=f"google_authorization_{error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="google_oauth_code_and_state_required")

    oauth_state = database.scalar(
        select(models.GoogleOAuthState).where(
            models.GoogleOAuthState.state_hash == _state_digest(state)
        )
    )
    now = datetime.utcnow()
    if oauth_state is None or oauth_state.used_at is not None or oauth_state.expires_at < now:
        raise HTTPException(status_code=400, detail="google_oauth_state_invalid_or_expired")
    cookie_name = STATE_COOKIE if oauth_state.purpose == "owner_login" else "max_google_oauth_state"
    if not secrets.compare_digest(state, request.cookies.get(cookie_name, "")):
        raise HTTPException(status_code=400, detail="google_oauth_code_and_state_required")

    # Mark before the network exchange so a callback URL cannot be replayed.
    oauth_state.used_at = now
    database.commit()
    client_id, client_secret, redirect_uri = _google_configuration()
    token_data = _exchange_code_for_tokens(code, client_id, client_secret, redirect_uri)
    if oauth_state.purpose == "owner_login":
        id_token = token_data.get("id_token")
        if not isinstance(id_token, str) or not id_token or not oauth_state.nonce_hash:
            raise HTTPException(status_code=502, detail="google_id_token_missing")
        email = verify_owner_id_token(id_token, oauth_state.nonce_hash)
        session, raw_token = create_owner_session(database, email)
        record_event(
            database,
            "owner_login",
            actor=email,
            record_type="owner_session",
            record_id=session.id,
        )
        database.commit()
        response = RedirectResponse(url=oauth_state.redirect_path or "/dashboard", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            raw_token,
            max_age=int(SESSION_LIFETIME.total_seconds()),
            httponly=True,
            secure=secure_cookie(request),
            samesite="lax",
            path="/",
        )
        response.delete_cookie(STATE_COOKIE, path="/google/oauth")
        return response
    refresh_token = token_data.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise HTTPException(status_code=502, detail="google_refresh_token_missing_restart_with_consent")

    safe_token = escape(refresh_token)
    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Google connected</title>
<style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:48px auto;padding:0 20px;color:#182230}}textarea{{width:100%;height:90px;font-family:monospace}}.warning{{background:#fff4d6;padding:14px;border-left:4px solid #c58b00}}</style>
</head><body><h1>Google authorization complete</h1>
<p>Copy this refresh token into the encrypted Vercel environment variable <code>GOOGLE_REFRESH_TOKEN</code>, then remove it from this page.</p>
<p class="warning"><strong>Keep it private.</strong> Max does not save or log this token. Do not paste it into Slack, GitHub, or a report.</p>
<textarea readonly id="token">{safe_token}</textarea><p><button onclick="navigator.clipboard.writeText(document.getElementById('token').value)">Copy token</button></p>
<p>Granted scopes: {escape(' '.join(GOOGLE_SCOPES))}</p></body></html>"""
    response = HTMLResponse(page)
    response.delete_cookie("max_google_oauth_state", path="/google/oauth")
    return response
