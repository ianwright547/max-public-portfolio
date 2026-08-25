"""Public read-only demo mode for the portfolio deployment.

The portfolio deployment shows the real dashboard running against seeded example
data instead of a description of it. Two properties keep that safe:

* Demo mode never engages on a deployment that has real owner auth configured,
  so a private instance can never silently fall back to open access.
* Every state-changing request is refused while it is on, so a visitor reads the
  product without being able to alter it.

Enable it with ``MAX_PUBLIC_DEMO=1`` and point ``MAX_DATABASE_URL`` at a
throwaway database. It is off unless that variable is explicitly set.
"""

from __future__ import annotations

import os

from app.auth_service import auth_is_configured


DEMO_OWNER_EMAIL = "owner@demo-agency.example"
# Reads are the only thing demo mode permits, so the browsing identity is given
# the role that renders every page. `required_capability` maps GET/HEAD/OPTIONS
# to "read", and unsafe methods never reach the capability check at all.
DEMO_ROLE = "owner"

_TRUE_VALUES = {"1", "true", "yes"}


def demo_mode_requested() -> bool:
    """Report whether the deployment asked for demo mode."""
    return os.getenv("MAX_PUBLIC_DEMO", "").strip().casefold() in _TRUE_VALUES


def demo_mode_enabled() -> bool:
    """Report whether demo mode is actually in force.

    A deployment that has real owner authentication configured keeps that
    authentication, whatever ``MAX_PUBLIC_DEMO`` says. Demo access is only ever
    a substitute for "no auth is configured at all".
    """
    return demo_mode_requested() and not auth_is_configured()
