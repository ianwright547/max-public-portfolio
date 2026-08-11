"""Run explicit read-only provider probes for active clients.

This command is intentionally opt-in: deployment operators can run it after
credentials and provider mappings are configured, while normal CI remains
network-free. It prints only client IDs, provider names, statuses, and safe
provider codes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.client_provider_verification import sweep_active_clients, verify_client_providers
from app.database import SessionLocal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe saved providers for active clients")
    parser.add_argument("--client-id", help="Probe one client instead of every active client")
    args = parser.parse_args(argv)
    with SessionLocal() as database:
        if args.client_id:
            client_ids = [args.client_id]
            if database.get(models.Client, args.client_id) is None:
                print(json.dumps({"status": "failed", "code": "client_not_found"}, sort_keys=True))
                return 1
        else:
            result = sweep_active_clients(database)
            database.commit()
            print(json.dumps(result, sort_keys=True))
            return 1 if result["status"] == "failed" else 0
        reports = []
        for client_id in client_ids:
            result = verify_client_providers(database, client_id)
            reports.append(
                {
                    "client_id": client_id,
                    "status": result["status"],
                    "summary": result["summary"],
                    "results": [
                        {
                            "provider": item["provider"],
                            "status": item["status"],
                            "code": item.get("code"),
                            "retryable": item.get("retryable", False),
                        }
                        for item in result["results"]
                    ],
                }
            )
        database.commit()
    payload = {"status": "failed" if any(item["status"] == "failed" for item in reports) else "verified", "clients": reports}
    print(json.dumps(payload, sort_keys=True))
    return 1 if payload["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
