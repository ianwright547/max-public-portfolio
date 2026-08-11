"""Run the same value-free launch readiness checks exposed by Max."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.readiness_service import build_readiness
from scripts import check_provider_connections
from scripts import check_search_console_connections
from scripts import check_slack_provider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("core", "full"), default="core")
    parser.add_argument(
        "--live-slack",
        action="store_true",
        help="after static full-profile checks, verify the Slack workspace and owner members",
    )
    parser.add_argument(
        "--live-providers",
        action="store_true",
        help="after static full-profile checks, verify GitHub, Vercel, and GBP mappings",
    )
    parser.add_argument(
        "--live-search-console",
        action="store_true",
        help="after static full-profile checks, query active client Search Console properties",
    )
    args = parser.parse_args(argv)
    if (args.live_slack or args.live_providers or args.live_search_console) and args.profile != "full":
        print("live provider checks require --profile full", file=sys.stderr)
        return 1
    with SessionLocal() as database:
        result = build_readiness(database, args.profile)
    print(f"Max launch readiness ({result['profile']})")
    for check in result["checks"]:
        print(f"[{check['status']}] {check['key']}: {check['detail']}")
        if check.get("remediation"):
            print(f"  Next: {check['remediation']}")
    summary = result["summary"]
    print(
        f"\n{summary['passed']} passed, {summary['blocked']} blocked, "
        f"{summary['total']} total."
    )
    if result["status"] != "ready":
        return 1
    if args.live_slack:
        print("\nLive Slack provider verification")
        if check_slack_provider.main() != 0:
            return 1
    if args.live_providers:
        print("\nLive GitHub/Vercel/GBP provider verification")
        if check_provider_connections.main() != 0:
            return 1
    if args.live_search_console:
        print("\nLive Search Console provider verification")
        return check_search_console_connections.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
