"""Validate deployment configuration without printing secret values.

Usage:
    python scripts/check_production_config.py
    python scripts/check_production_config.py --profile full
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

# Allow `python scripts/check_production_config.py` from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import read_database_url
from app.release_config import (
    billing_contract_valid,
    fulfillment_mode_valid,
    github_private_key_valid,
    https_origin,
    https_url,
    owner_emails_valid,
    positive_number,
    present,
)


@dataclass(frozen=True)
class Check:
    name: str
    valid: bool
    detail: str


def _checks(profile: str) -> list[Check]:
    checks = [
        Check(
            "MAX_DATABASE_URL",
            read_database_url().startswith(("postgresql://", "postgresql+psycopg://")),
            "must be a PostgreSQL URL for production",
        ),
        Check("AUTH_SECRET", present("AUTH_SECRET"), "must be set"),
        Check(
            "MAX_ALLOWED_GOOGLE_EMAILS",
            owner_emails_valid(),
            "must contain at least one valid owner email",
        ),
        Check("GOOGLE_CLIENT_ID", present("GOOGLE_CLIENT_ID"), "must be set"),
        Check("GOOGLE_CLIENT_SECRET", present("GOOGLE_CLIENT_SECRET"), "must be set"),
        Check("GOOGLE_REDIRECT_URI", https_url("GOOGLE_REDIRECT_URI"), "must be an HTTPS callback URL"),
        Check("JOB_RUNNER_SECRET", present("JOB_RUNNER_SECRET"), "must be set"),
        Check("CRON_SECRET", present("CRON_SECRET"), "must be set"),
    ]
    if profile == "full":
        checks.extend(
            [
                Check("SLACK_BOT_TOKEN", present("SLACK_BOT_TOKEN"), "must be set"),
                Check("SLACK_SIGNING_SECRET", present("SLACK_SIGNING_SECRET"), "must be set"),
                Check("SLACK_WORKSPACE_ID", present("SLACK_WORKSPACE_ID"), "must be set"),
                Check("SLACK_OWNER_USER_IDS", present("SLACK_OWNER_USER_IDS"), "must be set"),
                Check(
                    "MAX_PUBLIC_BASE_URL",
                    https_origin("MAX_PUBLIC_BASE_URL"),
                    "must be an HTTPS origin without a path",
                ),
                Check("OPENAI_API_KEY", present("OPENAI_API_KEY"), "must be set"),
                Check("GITHUB_APP_ID", present("GITHUB_APP_ID"), "must be set"),
                Check("GITHUB_APP_PRIVATE_KEY", github_private_key_valid(), "must be a PEM private key"),
                Check("GITHUB_APP_INSTALLATION_ID", present("GITHUB_APP_INSTALLATION_ID"), "must be set"),
                Check("GITHUB_OWNER", present("GITHUB_OWNER"), "must be set"),
                Check("GITHUB_REPOSITORY", present("GITHUB_REPOSITORY"), "must be set"),
                Check("VERCEL_API_TOKEN", present("VERCEL_API_TOKEN"), "must be set"),
                Check("VERCEL_PROJECT_ID", present("VERCEL_PROJECT_ID"), "must be set"),
                Check("GOOGLE_REFRESH_TOKEN", present("GOOGLE_REFRESH_TOKEN"), "must be set"),
                Check("GBP_ACCOUNT_ID", present("GBP_ACCOUNT_ID"), "must be set"),
                Check("GBP_LOCATION_ID", present("GBP_LOCATION_ID"), "must be set"),
                Check(
                    "MAX_FULFILLMENT_MODE",
                    fulfillment_mode_valid(),
                    "must explicitly select codex_handoff with writes disabled or github_vercel with writes enabled",
                ),
                Check(
                    "BILLING_CONTRACT",
                    billing_contract_valid(),
                    "must set BILLING_PROVIDER and BILLING_WEBHOOK_SECRET when billing enforcement is enabled",
                ),
            ]
        )
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("core", "full"), default="core")
    args = parser.parse_args(argv)

    checks = _checks(args.profile)
    print(f"Max production configuration ({args.profile})")
    for check in checks:
        state = "ok" if check.valid else "missing"
        print(f"[{state}] {check.name}: {check.detail}")
    failed = [check for check in checks if not check.valid]
    if failed:
        print(f"\n{len(failed)} configuration check(s) failed.", file=sys.stderr)
        return 1
    print("\nAll configuration checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
