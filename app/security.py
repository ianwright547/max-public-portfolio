"""Fail-closed request authentication and same-origin browser mutation checks."""

from __future__ import annotations

import re
from urllib.parse import quote, urlparse

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.auth_service import SESSION_COOKIE, auth_is_configured, auth_is_required, find_owner_session
from app.agency_access_service import has_capability, role_for_email
from app.database import SessionLocal


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
