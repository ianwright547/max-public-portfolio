"""Phase 5 metric, baseline, integration, and manual-entry endpoints."""

import calendar
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_database
from app.metric_rules import (
    SUPPORTED_METRICS,
    calculate_change,
    normalize_measurement_period,
    normalize_metric_value,
)
from app.notification_service import notify_metric_change
from app.routes.website_metrics import render_client_website_metrics

router = APIRouter(tags=["metrics"])

METRIC_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "metric_entry.html"


def require_client(database: Session, client_id: str) -> models.Client:
    """Return one client or stop before any child data can be created."""
    client = database.get(models.Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def ensure_integration(database: Session, client_id: str, source_type: str) -> models.IntegrationConnection:
    """Create or refresh the current data-source status for a client."""
    settings = {
        "manual": ("Manual entry", "available", []),
        "imported": ("Imported data", "available", []),
        "mock": (
            "Google Business Profile sample data",
            "mock_only",
            ["Google Business Profile API is not connected. Values are generated samples."],
        ),
        "live_api": ("Live API", "not_configured", ["No live connector is installed."]),
    }
    integration_name, connection_status, issues = settings[source_type]
    connection = database.scalar(
        select(models.IntegrationConnection).where(
            models.IntegrationConnection.client_id == client_id,
            models.IntegrationConnection.integration_name == integration_name,
            models.IntegrationConnection.data_source_type == source_type,
        )
    )
    if connection is None:
        connection = models.IntegrationConnection(
            client_id=client_id,
            integration_name=integration_name,
            connection_status=connection_status,
            data_source_type=source_type,
            issues=issues,
        )
        database.add(connection)
    connection.last_checked_at = datetime.utcnow()
    connection.connection_status = connection_status
    connection.issues = issues
    return connection


def add_metric_snapshot(
    database: Session,
    client_id: str,
    metric_name: str,
    value: Any,
    measurement_period: str,
    source_type: str,
    is_baseline: bool,
) -> models.MetricSnapshot:
    """Add a new snapshot without changing any older observation."""
    normalized_value = normalize_metric_value(metric_name, value)
    normalized_period = normalize_measurement_period(measurement_period)
    if is_baseline:
        existing_baseline = database.scalar(
            select(models.MetricSnapshot).where(
                models.MetricSnapshot.client_id == client_id,
                models.MetricSnapshot.metric_name == metric_name,
                models.MetricSnapshot.is_baseline.is_(True),
            )
        )
        if existing_baseline is not None:
            raise HTTPException(status_code=409, detail=f"A baseline already exists for {metric_name}")

    snapshot = models.MetricSnapshot(
        client_id=client_id,
        metric_name=metric_name,
        value=normalized_value,
        measurement_period=normalized_period,
        source_type=source_type,
        is_baseline=is_baseline,
    )
    database.add(snapshot)
    database.flush()
    notify_metric_change(database, snapshot)
    return snapshot


def metric_history(database: Session, client_id: str, metric_name: Optional[str] = None) -> list:
    """Return immutable history in measurement and recording order."""
    statement = select(models.MetricSnapshot).where(models.MetricSnapshot.client_id == client_id)
    if metric_name is not None:
        statement = statement.where(models.MetricSnapshot.metric_name == metric_name)
    statement = statement.order_by(
        models.MetricSnapshot.measurement_period,
        models.MetricSnapshot.recorded_at,
        models.MetricSnapshot.id,
    )
    return list(database.scalars(statement))


def build_comparison(database: Session, client_id: str, metric_name: str) -> dict:
    """Compare the latest snapshot with its baseline and previous period."""
    snapshots = metric_history(database, client_id, metric_name)
    if not snapshots:
        raise HTTPException(status_code=404, detail="Metric history not found")

    current = snapshots[-1]
    baseline = next((snapshot for snapshot in snapshots if snapshot.is_baseline), None)
    previous = next(
        (
            snapshot
            for snapshot in reversed(snapshots)
            if snapshot.measurement_period < current.measurement_period
        ),
        None,
    )

    return {
        "client_id": client_id,
        "metric_name": metric_name,
        "current": current,
        "baseline": baseline,
        "previous_period": previous,
        "change_from_baseline": (
            calculate_change(metric_name, current.value, baseline.value) if baseline is not None else None
        ),
        "change_from_previous": (
            calculate_change(metric_name, current.value, previous.value) if previous is not None else None
        ),
    }


def mock_values(client_id: str, measurement_period: str) -> dict:
    """Create predictable samples that vary by client and month."""
    seed = sum(ord(character) for character in f"{client_id}:{measurement_period}")
    year, month = (int(part) for part in measurement_period.split("-"))
    post_day = min(18 + seed % 10, calendar.monthrange(year, month)[1])
    today = date.today()
    if (year, month) == (today.year, today.month):
        post_day = min(post_day, today.day)
    return {
        "reviews": 18 + seed % 83,
        "rating": round(3.6 + (seed % 14) / 10, 1),
        "calls": 9 + seed % 47,
        "website_clicks": 22 + seed % 119,
        "direction_requests": 5 + seed % 36,
        "impressions": 680 + seed % 1900,
        "search_clicks": 31 + seed % 210,
        "last_google_post_date": f"{measurement_period}-{post_day:02d}",
    }


@router.post(
    "/clients/{client_id}/metrics",
    response_model=schemas.MetricRead,
    status_code=status.HTTP_201_CREATED,
)
def create_metric(
    client_id: str,
    metric: schemas.MetricCreate,
    database: Session = Depends(get_database),
) -> models.MetricSnapshot:
    """Save one manual or imported observation with an honest source label."""
    require_client(database, client_id)
    try:
        snapshot = add_metric_snapshot(database, client_id, **metric.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    ensure_integration(database, client_id, metric.source_type)
    database.commit()
    database.refresh(snapshot)
    return snapshot


@router.post(
    "/clients/{client_id}/metrics/mock",
    response_model=list[schemas.MetricRead],
    status_code=status.HTTP_201_CREATED,
)
def generate_mock_metrics(
    client_id: str,
    request: schemas.MockMetricRequest,
    database: Session = Depends(get_database),
) -> list[models.MetricSnapshot]:
    """Generate all sample metrics and permanently label them as mock."""
    require_client(database, client_id)
    values = mock_values(client_id, request.measurement_period)

    if request.mark_as_baseline:
        existing = database.scalar(
            select(models.MetricSnapshot).where(
                models.MetricSnapshot.client_id == client_id,
                models.MetricSnapshot.metric_name.in_(values),
                models.MetricSnapshot.is_baseline.is_(True),
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="At least one metric already has a baseline")

    snapshots = [
        add_metric_snapshot(
            database,
            client_id,
            metric_name,
            value,
            request.measurement_period,
            "mock",
            request.mark_as_baseline,
        )
        for metric_name, value in values.items()
    ]
    ensure_integration(database, client_id, "mock")
    database.commit()
    for snapshot in snapshots:
        database.refresh(snapshot)
    return snapshots


@router.get("/clients/{client_id}/metrics", response_model=list[schemas.MetricRead])
def read_metric_history(
    client_id: str,
    metric_name: Optional[str] = None,
    database: Session = Depends(get_database),
) -> list[models.MetricSnapshot]:
    """Return every snapshot; this endpoint never collapses history."""
    require_client(database, client_id)
    if metric_name is not None and metric_name not in SUPPORTED_METRICS:
        raise HTTPException(status_code=422, detail=f"Unsupported metric: {metric_name}")
    return metric_history(database, client_id, metric_name)


@router.get(
    "/clients/{client_id}/metrics/{metric_name}/comparison",
    response_model=schemas.MetricComparison,
)
def compare_metric(
    client_id: str,
    metric_name: str,
    database: Session = Depends(get_database),
) -> dict:
    """Compare a client's latest metric with baseline and previous period."""
    require_client(database, client_id)
    if metric_name not in SUPPORTED_METRICS:
        raise HTTPException(status_code=422, detail=f"Unsupported metric: {metric_name}")
    return build_comparison(database, client_id, metric_name)


@router.get("/clients/{client_id}/integrations", response_model=list[schemas.IntegrationRead])
def read_integrations(
    client_id: str,
    database: Session = Depends(get_database),
) -> list[models.IntegrationConnection]:
    """Show the current source and connection status for one client."""
    require_client(database, client_id)
    return list(
        database.scalars(
            select(models.IntegrationConnection)
            .where(models.IntegrationConnection.client_id == client_id)
            .order_by(models.IntegrationConnection.integration_name)
        )
    )


def render_history_rows(snapshots: list) -> str:
    """Render saved metric history for the manual browser screen."""
    if not snapshots:
        return '<p class="metrics-empty">No metric snapshots have been recorded for this client.</p>'
    rows = []
    for snapshot in reversed(snapshots):
        baseline = '<span class="baseline-label">Baseline</span>' if snapshot.is_baseline else ""
        rows.append(
            f"""
            <div class="metric-history-row">
              <span><strong>{escape(snapshot.metric_name.replace('_', ' ').title())}</strong>{baseline}</span>
              <span class="metric-value">{escape(str(snapshot.value))}</span>
              <span>{escape(snapshot.measurement_period)}</span>
              <span class="source-label source-{escape(snapshot.source_type)}">{escape(snapshot.source_type)}</span>
              <time datetime="{snapshot.recorded_at.isoformat()}">{snapshot.recorded_at.strftime('%b %d, %Y %H:%M')}</time>
            </div>
            """
        )
    return "".join(rows)


def format_change(change: Optional[dict]) -> str:
    """Turn one calculated change into short human-readable text."""
    if change is None:
        return "Not available"
    sign = "+" if change["amount"] > 0 else ""
    amount = f"{sign}{change['amount']:g} {change['unit']}"
    if change["percent"] is not None:
        amount += f" ({sign}{change['percent']:g}%)"
    return amount


def render_comparison_rows(database: Session, client_id: str) -> str:
    """Render comparison results for metrics that have saved history."""
    rows = []
    for metric_name in sorted(SUPPORTED_METRICS):
        snapshots = metric_history(database, client_id, metric_name)
        if not snapshots:
            continue
        comparison = build_comparison(database, client_id, metric_name)
        current = comparison["current"]
        rows.append(
            f"""
            <div class="comparison-row">
              <strong>{escape(metric_name.replace('_', ' ').title())}</strong>
              <span>{escape(str(current.value))}<small>{escape(current.measurement_period)}</small></span>
              <span>{escape(format_change(comparison['change_from_baseline']))}</span>
              <span>{escape(format_change(comparison['change_from_previous']))}</span>
            </div>
            """
        )
    if not rows:
        return '<p class="metrics-empty">Add at least one snapshot to begin comparisons.</p>'
    return "".join(rows)


def snapshots_by_period(database: Session, client_id: str, metric_name: str) -> list:
    """Return the newest saved snapshot for each measurement period."""
    newest_by_period = {}
    for snapshot in metric_history(database, client_id, metric_name):
        newest_by_period[snapshot.measurement_period] = snapshot
    return [newest_by_period[period] for period in sorted(newest_by_period)]


def change_text(current: Any, previous: Any) -> tuple[str, str]:
    """Return concise change text and a visual direction class."""
    if current is None or previous is None:
        return "No previous period", "change-neutral"
    difference = round(float(current) - float(previous), 2)
    sign = "+" if difference > 0 else ""
    direction = "change-up" if difference > 0 else "change-down" if difference < 0 else "change-neutral"
    if float(previous) == 0:
        return f"{sign}{difference:g} from previous", direction
    percent = round((difference / float(previous)) * 100, 1)
    return f"{sign}{difference:g} · {sign}{percent:g}%", direction


def period_label(measurement_period: str, short: bool = False) -> str:
    """Turn a stored YYYY-MM period into a label people can scan."""
    parsed = datetime.strptime(measurement_period, "%Y-%m")
    return parsed.strftime("%b") if short else parsed.strftime("%B %Y")


def render_summary_metric(
    database: Session,
    client_id: str,
    metric_name: str,
    label: str,
    compare_to_baseline: bool = False,
) -> str:
    """Render one current-value summary with an honest source label."""
    snapshots = snapshots_by_period(database, client_id, metric_name)
    if not snapshots:
        return f"""
          <article class="performance-stat empty-stat">
            <span>{escape(label)}</span><strong>—</strong><small>No data recorded</small>
          </article>
        """
    current = snapshots[-1]
    previous = snapshots[-2] if len(snapshots) > 1 else None
    if compare_to_baseline:
        baseline = next((snapshot for snapshot in metric_history(database, client_id, metric_name) if snapshot.is_baseline), None)
        comparison_value = baseline.value if baseline is not None else (previous.value if previous else None)
        comparison_label = "Baseline" if baseline is not None else "Previous month"
    else:
        comparison_value = previous.value if previous else None
        comparison_label = "Previous month"
    change, change_class = change_text(current.value, comparison_value)
    comparison_value_text = escape(str(comparison_value)) if comparison_value is not None else "—"
    return f"""
      <article class="performance-stat">
        <span>{escape(label)} <em>{escape(period_label(current.measurement_period, True))}</em></span>
        <div class="stat-comparison">
          <strong>{escape(str(current.value))}</strong>
          <span><small>{comparison_label}</small>{comparison_value_text}</span>
        </div>
        <small class="{change_class}">{escape(change)}</small>
        <em>{escape(period_label(current.measurement_period))} · {escape(current.source_type.title())}</em>
      </article>
    """


def render_trend_chart(snapshots: list, metric_name: str) -> str:
    """Render a responsive SVG line chart without an external dependency."""
    if not snapshots:
        return '<p class="chart-empty">No snapshots are available for this metric.</p>'
    values = [float(snapshot.value) for snapshot in snapshots]
    minimum = min(values)
    maximum = max(values)
    spread = maximum - minimum or 1
    left, top, width, height = 52, 28, 616, 144
    step = width / max(len(snapshots) - 1, 1)
    points = []
    labels = []
    circles = []
    value_labels = []
    for index, snapshot in enumerate(snapshots):
        x = left + index * step if len(snapshots) > 1 else left + width / 2
        y = top + height - ((float(snapshot.value) - minimum) / spread) * height
        points.append(f"{x:.1f},{y:.1f}")
        point_class = " current-point" if index == len(snapshots) - 1 else ""
        circles.append(f'<circle class="{point_class}" cx="{x:.1f}" cy="{y:.1f}" r="4"><title>{escape(period_label(snapshot.measurement_period))}: {escape(str(snapshot.value))}</title></circle>')
        value_labels.append(f'<text class="point-value" x="{x:.1f}" y="{max(y - 10, 14):.1f}" text-anchor="middle">{escape(str(snapshot.value))}</text>')
        labels.append(f'<text class="month-label" x="{x:.1f}" y="205" text-anchor="middle">{escape(period_label(snapshot.measurement_period, True))}</text>')
    area_points = f"{left},172 " + " ".join(points) + f" {left + width},172"
    midpoint = (maximum + minimum) / 2
    return f"""
      <svg class="trend-svg" viewBox="0 0 720 225" role="img" aria-label="{escape(metric_name.replace('_', ' '))} trend chart">
        <line class="grid-line" x1="52" y1="28" x2="668" y2="28"></line>
        <line class="grid-line" x1="52" y1="100" x2="668" y2="100"></line>
        <line class="grid-line" x1="52" y1="172" x2="668" y2="172"></line>
        <text class="axis-value" x="44" y="31" text-anchor="end">{maximum:g}</text>
        <text class="axis-value" x="44" y="103" text-anchor="end">{midpoint:g}</text>
        <text class="axis-value" x="44" y="175" text-anchor="end">{minimum:g}</text>
        <polygon class="trend-area" points="{area_points}"></polygon>
        <polyline class="trend-line" points="{' '.join(points)}"></polyline>
        {''.join(circles)}
        {''.join(value_labels)}
        {''.join(labels)}
      </svg>
    """


def render_performance_dashboard(
    database: Session,
    client_id: str,
    focus_metric: str,
    period_count: int,
) -> str:
    """Render the Phase 5 overview from the same immutable snapshots as the API."""
    post_snapshots = snapshots_by_period(database, client_id, "last_google_post_date")
    last_post = post_snapshots[-1] if post_snapshots else None
    if last_post is None:
        post_value = "No post date recorded"
        post_meta = "Add a manual, imported, or mock value"
    else:
        post_value = date.fromisoformat(str(last_post.value)).strftime("%B %Y")
        post_meta = f"Saved as {last_post.source_type.title()} data"

    trend_snapshots = snapshots_by_period(database, client_id, focus_metric)[-period_count:]
    selected_options = "".join(
        f'<option value="{metric}"{" selected" if metric == focus_metric else ""}>{metric.replace("_", " ").title()}</option>'
        for metric in sorted(SUPPORTED_METRICS - {"last_google_post_date"})
    )
    period_options = "".join(
        f'<option value="{count}"{" selected" if count == period_count else ""}>Last {count} periods</option>'
        for count in (3, 6, 12)
    )
    latest_source = trend_snapshots[-1].source_type if trend_snapshots else "no data"
    return f"""
      <section class="performance-overview" aria-labelledby="overview-title">
        <header class="performance-heading">
          <div><h2 id="overview-title">Performance overview</h2><p>Current period compared with saved history.</p></div>
          <span class="dashboard-source">Chart source: {escape(latest_source)}</span>
        </header>
        <div class="performance-stats">
          {render_summary_metric(database, client_id, 'calls', 'Calls')}
          {render_summary_metric(database, client_id, 'reviews', 'Reviews', True)}
          {render_summary_metric(database, client_id, 'direction_requests', 'Direction requests')}
          {render_summary_metric(database, client_id, 'website_clicks', 'Website clicks')}
        </div>
        <div class="performance-grid">
          <section class="trend-panel">
            <header>
              <div><h3>{escape(focus_metric.replace('_', ' ').title())} by month</h3><p>{len(trend_snapshots)} months shown · values labeled on the line</p></div>
              <form class="chart-controls" method="get" action="/dashboard/clients/{escape(client_id)}/metrics">
                <select name="focus_metric" aria-label="Chart metric">{selected_options}</select>
                <select name="periods" aria-label="Chart period count">{period_options}</select>
                <button type="submit">Update</button>
              </form>
            </header>
            {render_trend_chart(trend_snapshots, focus_metric)}
          </section>
          <aside class="last-post-panel">
            <span>Last Google post</span>
            <strong>{escape(post_value)}</strong>
            <small>{escape(post_meta)}</small>
            <p>This is the saved post date, not a live Google check.</p>
          </aside>
        </div>
      </section>
    """


@router.get("/dashboard/clients/{client_id}/metrics", response_class=HTMLResponse)
def metric_entry_page(
    client_id: str,
    saved: Optional[str] = None,
    error: Optional[str] = None,
    focus_metric: str = "calls",
    periods: int = 6,
    database: Session = Depends(get_database),
) -> HTMLResponse:
    """Show manual entry, mock generation, source status, and full history."""
    client = require_client(database, client_id)
    if focus_metric not in SUPPORTED_METRICS or focus_metric == "last_google_post_date":
        focus_metric = "calls"
    if periods not in {3, 6, 12}:
        periods = 6
    snapshots = metric_history(database, client_id)
    integrations = list(
        database.scalars(
            select(models.IntegrationConnection).where(
                models.IntegrationConnection.client_id == client_id
            )
        )
    )
    integration_text = "No data sources used yet."
    if integrations:
        integration_text = " · ".join(
            f"{connection.integration_name}: {connection.connection_status} ({connection.data_source_type})"
            for connection in integrations
        )
    notice = ""
    if saved:
        notice = '<p class="form-notice success-notice">Metric data saved.</p>'
    if error:
        notice = f'<p class="form-notice error-notice">{escape(error)}</p>'

    options = "".join(
        f'<option value="{metric}">{metric.replace("_", " ").title()}</option>'
        for metric in sorted(SUPPORTED_METRICS)
    )
    template = METRIC_TEMPLATE_PATH.read_text(encoding="utf-8")
    page = (
        template.replace("{{CLIENT_ID}}", escape(client.id))
        .replace("{{BUSINESS_NAME}}", escape(client.business_name))
        .replace("{{METRIC_OPTIONS}}", options)
        .replace("{{NOTICE}}", notice)
        .replace("{{INTEGRATIONS}}", escape(integration_text))
        .replace(
            "{{PERFORMANCE_DASHBOARD}}",
            render_performance_dashboard(database, client_id, focus_metric, periods),
        )
        .replace("{{WEBSITE_METRICS}}", render_client_website_metrics(database, client_id))
        .replace("{{COMPARISON_ROWS}}", render_comparison_rows(database, client_id))
        .replace("{{HISTORY_ROWS}}", render_history_rows(snapshots))
    )
    return HTMLResponse(page)


async def form_values(request: Request) -> dict[str, str]:
    """Read a basic HTML form without adding a multipart dependency."""
    values = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    return {key: entries[-1] for key, entries in values.items()}


@router.post("/dashboard/clients/{client_id}/metrics/manual", response_class=RedirectResponse)
async def submit_manual_metric(
    client_id: str,
    request: Request,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    """Save a manual metric from the browser form."""
    require_client(database, client_id)
    values = await form_values(request)
    try:
        snapshot = add_metric_snapshot(
            database,
            client_id,
            values.get("metric_name", ""),
            values.get("value", ""),
            values.get("measurement_period", ""),
            "manual",
            values.get("is_baseline") == "on",
        )
        ensure_integration(database, client_id, "manual")
        database.commit()
        database.refresh(snapshot)
    except (ValueError, HTTPException) as error:
        database.rollback()
        detail = error.detail if isinstance(error, HTTPException) else str(error)
        return RedirectResponse(
            url=f"/dashboard/clients/{client_id}/metrics?error={quote(detail)}",
            status_code=303,
        )
    return RedirectResponse(url=f"/dashboard/clients/{client_id}/metrics?saved=1", status_code=303)


@router.post("/dashboard/clients/{client_id}/metrics/mock", response_class=RedirectResponse)
async def submit_mock_metrics(
    client_id: str,
    request: Request,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    """Generate clearly labeled mock values from the browser screen."""
    values = await form_values(request)
    try:
        request_model = schemas.MockMetricRequest(
            measurement_period=values.get("measurement_period", ""),
            mark_as_baseline=values.get("mark_as_baseline") == "on",
        )
        generate_mock_metrics(client_id, request_model, database)
    except (ValidationError, ValueError, HTTPException) as error:
        database.rollback()
        detail = getattr(error, "detail", str(error))
        return RedirectResponse(
            url=f"/dashboard/clients/{client_id}/metrics?error={quote(str(detail))}",
            status_code=303,
        )
    return RedirectResponse(url=f"/dashboard/clients/{client_id}/metrics?saved=1", status_code=303)
