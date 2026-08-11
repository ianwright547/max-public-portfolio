"""Value-free validation helpers shared by release gates.

These checks intentionally validate only shape and consistency. They never
return, log, or include the configured values themselves.
"""

from __future__ import annotations

import math
import os
import re
from urllib.parse import urlparse


_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def present(*names: str) -> bool:
    return all(bool(os.getenv(name, "").strip()) for name in names)


def https_url(name: str, *, allow_path: bool = True) -> bool:
    parsed = urlparse(os.getenv(name, "").strip())
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    return allow_path or parsed.path in {"", "/"}


def https_origin(name: str) -> bool:
    return https_url(name, allow_path=False)


def positive_number(name: str) -> bool:
    try:
        value = float(os.getenv(name, ""))
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value > 0


def owner_emails_valid(name: str = "MAX_ALLOWED_GOOGLE_EMAILS") -> bool:
    values = [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]
    return bool(values) and all(_EMAIL_RE.fullmatch(value) for value in values)


def github_private_key_valid(name: str = "GITHUB_APP_PRIVATE_KEY") -> bool:
    value = os.getenv(name, "").strip().replace("\\n", "\n")
    return "-----BEGIN" in value and "PRIVATE KEY-----" in value and "-----END" in value


def fulfillment_mode_valid() -> bool:
    mode = os.getenv("MAX_FULFILLMENT_MODE", "").strip().casefold()
    writes = os.getenv("MAX_ENABLE_EXTERNAL_WRITES", "").strip().casefold() in {"1", "true", "yes"}
    return (mode == "codex_handoff" and not writes) or (mode == "github_vercel" and writes)


def browser_worker_pair_valid() -> bool:
    url = os.getenv("BROWSER_WORKER_URL", "").strip()
    token = os.getenv("BROWSER_WORKER_TOKEN", "").strip()
    if not url and not token:
        return True
    parsed = urlparse(url)
    return bool(url and token and parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password)


def billing_contract_valid() -> bool:
    """Paid-mode enforcement requires a provider label and signed webhook secret."""
    enabled = os.getenv("MAX_BILLING_ENFORCEMENT", "").strip().casefold() in {"1", "true", "yes"}
    return not enabled or present("BILLING_PROVIDER", "BILLING_WEBHOOK_SECRET")
