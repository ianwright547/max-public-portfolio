"""Verify active client Search Console properties with read-only queries."""

from __future__ import annotations

from datetime import date, timedelta
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app import models
from app.database import SessionLocal
from app.google_search_console_service import GoogleSearchConsoleAdapter, SearchConsoleIntegrationError


MAX_PROPERTIES = 50


def verify_connections(database, *, adapter=None, end_date: date | None = None) -> dict[str, object]:
    connections = list(
        database.scalars(
            select(models.SearchConsoleConnection)
            .join(models.Client, models.Client.id == models.SearchConsoleConnection.client_id)
            .where(models.Client.archived_at.is_(None))
            .order_by(models.SearchConsoleConnection.id)
            .limit(MAX_PROPERTIES)
        )
    )
    if not connections:
        return {"status": "skipped", "checked_properties": 0, "properties_with_data": 0}
    search_console = adapter or GoogleSearchConsoleAdapter()
    end = end_date or date.today() - timedelta(days=3)
    start = end - timedelta(days=6)
    properties_with_data = 0
    for connection in connections:
        try:
            report = search_console.read_report(
                connection.property_url,
                start.isoformat(),
                end.isoformat(),
            )
        except SearchConsoleIntegrationError:
            raise
        if report.metrics.has_data:
            properties_with_data += 1
    return {
        "status": "verified",
        "checked_properties": len(connections),
        "properties_with_data": properties_with_data,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
    }


def main() -> int:
    try:
        with SessionLocal() as database:
            result = verify_connections(database)
    except SearchConsoleIntegrationError as error:
        print(f"Search Console verification failed: {error.code}", file=sys.stderr)
        return 1
    except Exception:
        print("Search Console verification failed: search_console_probe_failed", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
