"""Fail-closed request authentication and same-origin browser mutation checks."""

from __future__ import annotations

import re
from urllib.parse import quote, urlparse

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.auth_service import SESSION_COOKIE, auth_is_configured, auth_is_required, find_owner_session
from app.agency_access_service import has_capability, role_for_email
from app.database import SessionLocal
from app.demo_mode import DEMO_OWNER_EMAIL, DEMO_ROLE, demo_mode_enabled


EXEMPT_PATHS = {
    # The root is a static description of the project. It renders no client
    # data and touches no database, so it stays readable on a public
    # deployment while every application route below remains fail-closed.
    "/",
    "/health",
    "/health/details",
    "/health/readiness",
    # OpenAPI is contract metadata only. Keeping it public lets the
    # deployment smoke test verify the shipped surface without weakening any
    # client-data or mutation endpoint.
    "/openapi.json",
    "/google/oauth/callback",
    "/jobs/run-due",
    "/jobs/migrate",
    "/slack/actions",
    "/slack/events",
    "/billing/webhook",
}
EXEMPT_PREFIXES = ("/auth/login", "/static/")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

DEMO_READ_ONLY_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Read-only demo</title></head>
<body style="margin:0;min-height:100vh;display:flex;align-items:center;
justify-content:center;background:#f7f8fa;color:#0f172a;
font:16px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
<div style="max-width:32rem;padding:40px 32px;text-align:center;">
<p style="margin:0 0 10px;font-size:12px;font-weight:700;letter-spacing:2px;
text-transform:uppercase;color:#4f46e5;">Read-only demo</p>
<h1 style="margin:0 0 14px;font-size:26px;letter-spacing:-0.02em;">
That control is real, but it is switched off here</h1>
<p style="margin:0 0 24px;color:#5b6474;">
This deployment is a public demo running on invented data. It answers every
read, and refuses everything that would change state, so the sample portfolio
stays the same for the next visitor.</p>
<a href="/dashboard" style="display:inline-block;padding:11px 20px;
border-radius:9px;background:#4f46e5;color:#fff;font-size:14px;font-weight:600;
text-decoration:none;">Back to the dashboard</a>
</div></body></html>"""


def _is_exempt(path: str) -> bool:
    return (
        path in EXEMPT_PATHS
        or any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES)
        or re.fullmatch(r"/reports/[^/]+/share/[^/]+/pdf", path) is not None
    )


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin", "")
    if not origin:
        return False
    origin_url = urlparse(origin)
    return origin_url.scheme in {"http", "https"} and origin_url.netloc.casefold() == request.headers.get(
        "host", ""
    ).casefold()


def required_capability(path: str, method: str) -> str:
    """Classify the minimum role capability for one authenticated request."""
    normalized = path.casefold()
    if normalized == "/auth/logout" or method in {"GET", "HEAD", "OPTIONS"}:
        if normalized.startswith("/agency/members") or normalized.startswith("/dashboard/agency/members"):
            return "manage_members"
        if normalized.endswith("/pdf") and normalized.startswith("/reports/"):
            return "reporting"
        return "read"
    if normalized.startswith("/agency/members") or normalized.startswith("/dashboard/agency/members"):
        return "manage_members"
    if normalized.startswith("/billing") or normalized.endswith("/subscription"):
        return "billing"
    if normalized.startswith("/reports") or normalized.startswith("/metrics") or normalized.startswith("/website-metrics"):
        return "reporting"
    if any(
        normalized.startswith(prefix)
        for prefix in ("/fulfillment", "/codex", "/website", "/browser", "/google-business", "/search-console")
    ):
        return "fulfillment"
    return "client_operations"


async def enforce_request_security(request: Request, call_next):
    path = request.url.path
    if _is_exempt(path):
        return await call_next(request)
    if not auth_is_configured():
        if demo_mode_enabled():
            # The public demo is readable but immutable. Refusing every unsafe
            # method here means no route, form, or job can be reached in a way
            # that changes state, whatever the rest of the app would allow.
            if request.method in UNSAFE_METHODS:
                if _wants_html(request):
                    # A visitor who clicks a real control should get an
                    # explanation and a way back, not a raw JSON body.
                    return HTMLResponse(DEMO_READ_ONLY_PAGE, status_code=403)
                return JSONResponse(
                    {"detail": "demo_is_read_only"}, status_code=403
                )
            request.state.owner_email = DEMO_OWNER_EMAIL
            request.state.agency_role = DEMO_ROLE
            request.state.demo_mode = True
            return await call_next(request)
        if auth_is_required():
            return JSONResponse({"detail": "owner_auth_not_configured"}, status_code=503)
        request.state.owner_email = "local-development"
        return await call_next(request)
    with SessionLocal() as database:
        session = find_owner_session(database, request.cookies.get(SESSION_COOKIE, ""))
        role = role_for_email(database, session.email) if session is not None else ""
    if session is None:
        if request.method == "GET" and _wants_html(request):
            next_path = quote(path + (f"?{request.url.query}" if request.url.query else ""), safe="/?=&")
            return RedirectResponse(url=f"/auth/login?next={next_path}", status_code=307)
        return JSONResponse({"detail": "authentication_required"}, status_code=401)
    request.state.owner_email = session.email
    request.state.owner_session_id = session.id
    capability = required_capability(path, request.method)
    if not has_capability(role, capability):
        return JSONResponse({"detail": f"agency_role_{capability}_required"}, status_code=403)
    request.state.agency_role = role
    if request.method in UNSAFE_METHODS and not _same_origin(request):
        return JSONResponse({"detail": "csrf_origin_invalid"}, status_code=403)
    return await call_next(request)
