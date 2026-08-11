"""Verify the configured Slack bot can identify the expected workspace.

This is a read-only production probe. It calls Slack ``auth.test`` and never
prints the bot token or raw provider error text.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow ``python scripts/check_slack_provider.py`` from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.slack_service import SlackIntegrationError, get_slack_adapter, slack_owner_user_ids


def main() -> int:
    configured_workspace = os.getenv("SLACK_WORKSPACE_ID", "").strip()
    if not os.getenv("SLACK_BOT_TOKEN", "").strip():
        print("Slack verification failed: slack_token_missing", file=sys.stderr)
        return 1
    if not configured_workspace:
        print("Slack verification failed: slack_workspace_id_missing", file=sys.stderr)
        return 1
    owner_ids = slack_owner_user_ids()
    if not owner_ids:
        print("Slack verification failed: slack_owner_user_ids_missing", file=sys.stderr)
        return 1

    try:
        adapter = get_slack_adapter()
        workspace = adapter.verify_workspace()
    except SlackIntegrationError as error:
        print(f"Slack verification failed: {error.code}", file=sys.stderr)
        return 1
    except Exception:
        # Keep unexpected SDK/network details out of deployment logs.
        print("Slack verification failed: slack_probe_failed", file=sys.stderr)
        return 1

    if workspace.id != configured_workspace:
        print("Slack verification failed: slack_workspace_mismatch", file=sys.stderr)
        return 1
    if not workspace.bot_user_id:
        print("Slack verification failed: slack_bot_identity_missing", file=sys.stderr)
        return 1

    try:
        for owner_id in owner_ids:
            owner = adapter.get_user(owner_id)
            if owner.id != owner_id:
                print("Slack verification failed: slack_owner_identity_mismatch", file=sys.stderr)
                return 1
            if owner.deleted or owner.is_bot:
                print("Slack verification failed: slack_owner_user_inactive", file=sys.stderr)
                return 1
    except SlackIntegrationError as error:
        print(f"Slack verification failed: {error.code}", file=sys.stderr)
        return 1
    except Exception:
        print("Slack verification failed: slack_owner_probe_failed", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "verified",
                "workspace_id": workspace.id,
                "workspace_name": workspace.name,
                "bot_user_id_present": True,
                "owner_ids_configured": len(owner_ids),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
