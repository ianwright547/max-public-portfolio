"""Import aggregate website analytics from the existing public dashboard RPC."""

import json
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.request import Request, urlopen

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models


SOURCE_NAME = "website_analytics_dashboard"
# The analytics endpoint and its publishable key are read from the environment so
# this public copy of the project does not name a real backend. Configure
# WEBSITE_ANALYTICS_RPC_URL and WEBSITE_ANALYTICS_KEY in a private deployment.
RPC_URL = os.getenv("WEBSITE_ANALYTICS_RPC_URL", "").strip()
PUBLISHABLE_KEY = os.getenv("WEBSITE_ANALYTICS_KEY", "").strip()
MANIFEST = Path(__file__).parent.parent / "data" / "vercel_client_import.json"


def _set_integration_status(
    database: Session,
    client_id: str,
    status_value: str,
    issues: list[str],
    checked_at: datetime,
) -> None:
    integration = database.scalar(
        select(models.IntegrationConnection).where(
            models.IntegrationConnection.client_id == client_id,
            models.IntegrationConnection.integration_name == "Website analytics dashboard",
            models.IntegrationConnection.data_source_type == "live_api",
        )
    )
    if integration is None:
        integration = models.IntegrationConnection(
            client_id=client_id,
            integration_name="Website analytics dashboard",
            data_source_type="live_api",
            connection_status=status_value,
            issues=issues,
        )
        database.add(integration)
    integration.connection_status = status_value
    integration.last_checked_at = checked_at
    integration.issues = issues


def count_value(row: dict, field: str) -> int:
    """Require aggregate tracker counts to be non-negative whole numbers."""
    value = row.get(field, 0)
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a non-negative whole number")
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a non-negative whole number")
    if numeric < 0 or not numeric.is_integer():
        raise ValueError(f"{field} must be a non-negative whole number")
    return int(numeric)


def fetch_summary(period_start: datetime, period_end: datetime) -> list[dict]:
    if not RPC_URL or not PUBLISHABLE_KEY:
        # ValueError is what the sync route and the portfolio report already treat
        # as an unavailable analytics source, so an unconfigured deployment reports
        # the access gap instead of aborting the surrounding report.
        raise ValueError(
            "website analytics is not configured: set WEBSITE_ANALYTICS_RPC_URL "
            "and WEBSITE_ANALYTICS_KEY"
        )
    payload = json.dumps(
        {"p_from": period_start.isoformat(), "p_to": period_end.isoformat()}
    ).encode("utf-8")
    request = Request(
        RPC_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "apikey": PUBLISHABLE_KEY,
            "Authorization": f"Bearer {PUBLISHABLE_KEY}",
        },
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def sync_website_metrics(
    database: Session,
    window_days: int,
    fetcher: Callable[[datetime, datetime], list[dict]] = fetch_summary,
    today: Optional[date] = None,
) -> tuple[list[models.WebsiteMetricSnapshot], list[str], bool]:
    """Save one daily snapshot per real client, reusing the same day if repeated."""
    if window_days not in {7, 30, 90}:
        raise ValueError("window_days must be 7, 30, or 90")
    end_date = today or date.today()
    start_date = end_date - timedelta(days=window_days)

    mappings: list[tuple[models.Client, list[str]]] = []
    connected_client_ids: set[str] = set()
    for connection in database.scalars(select(models.WebsiteAnalyticsConnection)):
        client = database.get(models.Client, connection.client_id)
        if client is not None:
            mappings.append((client, connection.tracker_sites))
            connected_client_ids.add(client.id)

    # Compatibility while an installation is being backfilled. Once any
    # durable mapping exists, use only those mappings; mixing a stale manifest
    # with current records makes same-day cache coverage ambiguous.
    if not connected_client_ids:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for item in manifest:
            client = database.scalar(
                select(models.Client).where(
                    func.lower(models.Client.business_name) == item["business_name"].lower()
                )
            )
            if client is not None:
                mappings.append((client, item.get("tracker_sites", [])))

    existing = list(
        database.scalars(
            select(models.WebsiteMetricSnapshot).where(
                models.WebsiteMetricSnapshot.window_days == window_days,
                models.WebsiteMetricSnapshot.period_end == end_date,
                models.WebsiteMetricSnapshot.source == SOURCE_NAME,
            )
        )
    )
    existing_client_ids = {snapshot.client_id for snapshot in existing}
    existing_by_client = {snapshot.client_id: snapshot for snapshot in existing}
    mapped_client_ids = {client.id for client, _tracker_sites in mappings}
    # Manifest-only installations have no durable mapping signal for a newly
    # added client. Preserve the historical same-day cache behavior there;
    # explicit WebsiteAnalyticsConnection records use the stricter per-client
    # coverage check below.
    if existing and not connected_client_ids:
        return existing, [], True
    if existing and mapped_client_ids.issubset(existing_client_ids):
        return existing, [], True

    start_time = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end_time = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
    try:
        rows = fetcher(start_time, end_time)
    except Exception:
        checked_at = datetime.utcnow()
        for connection in database.scalars(select(models.WebsiteAnalyticsConnection)):
            _set_integration_status(
                database,
                connection.client_id,
                "error",
                ["website_analytics_sync_failed"],
                checked_at,
            )
        database.commit()
        raise
    rows_by_site = {str(row["site"]): row for row in rows}
    mapped_sites = set()
    snapshots = list(existing)

    for client, tracker_sites in mappings:
        if client.id in existing_by_client:
            continue
        available_rows = [rows_by_site[site] for site in tracker_sites if site in rows_by_site]
        mapped_sites.update(site for site in tracker_sites if site in rows_by_site)
        if not available_rows:
            _set_integration_status(
                database,
                client.id,
                "not_enough_data",
                ["No analytics row matched the client's saved tracker site."],
                datetime.utcnow(),
            )
            continue
        snapshot = models.WebsiteMetricSnapshot(
            client_id=client.id,
            period_start=start_date,
            period_end=end_date,
            window_days=window_days,
            unique_visitors=sum(count_value(row, "unique_visitors") for row in available_rows),
            pageviews=sum(count_value(row, "pageviews") for row in available_rows),
            call_clicks=sum(count_value(row, "call_clicks") for row in available_rows),
            form_submits=sum(count_value(row, "form_submits") for row in available_rows),
            tracker_sites=[str(row["site"]) for row in available_rows],
            source=SOURCE_NAME,
        )
        database.add(snapshot)
        snapshots.append(snapshot)

        _set_integration_status(database, client.id, "connected", [], datetime.utcnow())

    database.commit()
    for snapshot in snapshots:
        database.refresh(snapshot)
    unmatched = sorted(set(rows_by_site) - mapped_sites)
    return snapshots, unmatched, bool(existing)
