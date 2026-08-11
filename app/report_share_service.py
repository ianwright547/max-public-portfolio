"""Expiring, revocable client-report share links.

Client links are deliberately separate from owner-authenticated report routes.
The token contains no report data; it is an HMAC over the report ID and issue
time, while revocation and approval state remain authoritative in the database.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import hmac
import os
import calendar
from typing import Optional

from fastapi import HTTPException

from app import models


SHARE_TTL = timedelta(days=90)
_LOCAL_SECRET = "max-local-report-share-secret"


def _secret() -> bytes:
    configured = os.getenv("REPORT_SHARE_SECRET", "").strip() or os.getenv("AUTH_SECRET", "").strip()
    if configured:
        return configured.encode("utf-8")
    # Tests/local development still get deterministic links. A configured
    # deployment always has AUTH_SECRET and therefore never uses this value.
    return _LOCAL_SECRET.encode("utf-8")


def _signature(report_id: str, issued_at: int) -> str:
    payload = f"{report_id}:{issued_at}".encode("utf-8")
    return hmac.new(_secret(), payload, hashlib.sha256).hexdigest()


def issue_report_share_token(report: models.Report, now: Optional[datetime] = None) -> str:
    """Issue or reuse the stable token for one approved report version."""
    issued = report.client_share_issued_at or now or datetime.utcnow()
    if report.client_share_issued_at is None:
        report.client_share_issued_at = issued
    # Database timestamps are naive UTC values; ``datetime.timestamp()`` would
    # reinterpret them in the host's local timezone. Use UTC explicitly so a
    # link issued on a developer laptop validates identically in production.
    issued_epoch = calendar.timegm(issued.utctimetuple())
    return f"{issued_epoch}.{_signature(report.id, issued_epoch)}"


def share_path(report: models.Report, token: str) -> str:
    return f"/reports/{report.id}/share/{token}/pdf"


def validate_report_share(
    report: models.Report,
    token: str,
    now: Optional[datetime] = None,
) -> None:
    """Raise a non-enumerating 404 unless the share is currently valid."""
    not_found = HTTPException(status_code=404, detail="Report share not found or expired")
    if report.report_type != "client" or report.status != "approved":
        raise not_found
    if report.client_share_issued_at is None or report.client_share_revoked_at is not None:
        raise not_found
    try:
        issued_epoch_text, supplied_signature = token.split(".", 1)
        issued_epoch = int(issued_epoch_text)
    except (AttributeError, ValueError):
        raise not_found
    issued = datetime.utcfromtimestamp(issued_epoch)
    expected = _signature(report.id, issued_epoch)
    if not hmac.compare_digest(supplied_signature, expected):
        raise not_found
    if issued != report.client_share_issued_at.replace(microsecond=0):
        raise not_found
    current = now or datetime.utcnow()
    if current < issued or current > issued + SHARE_TTL:
        raise not_found
