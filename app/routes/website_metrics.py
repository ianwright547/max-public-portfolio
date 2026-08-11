"""Website analytics import API and portfolio dashboard."""

from html import escape
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_database
from app.website_analytics import SOURCE_NAME, sync_website_metrics

router = APIRouter(tags=["website metrics"])
TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "overall_metrics.html"


def require_client(database: Session, client_id: str) -> models.Client:
    client = database.get(models.Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def website_history(database: Session, client_id: str, window_days: int = 30) -> list:
    return list(
        database.scalars(
            select(models.WebsiteMetricSnapshot)
            .where(
                models.WebsiteMetricSnapshot.client_id == client_id,
                models.WebsiteMetricSnapshot.window_days == window_days,
            )
            .order_by(
                models.WebsiteMetricSnapshot.period_end,
                models.WebsiteMetricSnapshot.recorded_at,
            )
        )
    )


def latest_portfolio_snapshots(database: Session, window_days: int) -> list:
    clients = list(
        database.scalars(
            select(models.Client)
            .join(models.WebsiteConnection, models.WebsiteConnection.client_id == models.Client.id)
            .where(models.WebsiteConnection.source == "confirmed_vercel_import")
            .order_by(models.Client.business_name)
        )
    )
    snapshots = []
    for client in clients:
        history = website_history(database, client.id, window_days)
        if history:
            snapshots.append(history[-1])
    return snapshots


@router.post(
    "/website-metrics/sync",
    response_model=schemas.WebsiteMetricSyncRead,
    status_code=status.HTTP_201_CREATED,
)
def sync_metrics(
    request: schemas.WebsiteMetricSyncRequest,
    database: Session = Depends(get_database),
) -> dict:
    try:
        snapshots, unmatched, reused = sync_website_metrics(database, request.window_days)
    except (URLError, TimeoutError, ValueError) as error:
        database.rollback()
        raise HTTPException(status_code=502, detail=f"Website analytics sync failed: {error}")
    return {
        "snapshots": snapshots,
        "unmatched_tracker_sites": unmatched,
        "reused_existing": reused,
    }


@router.get(
    "/clients/{client_id}/website-metrics",
    response_model=list[schemas.WebsiteMetricRead],
)
def read_client_website_metrics(
    client_id: str,
    window_days: int = 30,
    database: Session = Depends(get_database),
) -> list[models.WebsiteMetricSnapshot]:
    require_client(database, client_id)
    if window_days not in {7, 30, 90}:
        raise HTTPException(status_code=422, detail="window_days must be 7, 30, or 90")
    return website_history(database, client_id, window_days)


def metric_card(label: str, value: str, note: str) -> str:
    return f'<article><span>{escape(label)}</span><strong>{escape(value)}</strong><small>{escape(note)}</small></article>'


def render_client_website_metrics(database: Session, client_id: str) -> str:
    history = website_history(database, client_id, 30)
    if not history:
        return """
          <section class="website-metrics-section">
            <header><div><h2>Website analytics</h2><p>No website analytics snapshot has been imported for this client.</p></div><a href="/dashboard/metrics">Open overall metrics</a></header>
          </section>
        """
    current = history[-1]
    conversion = (current.call_clicks / current.unique_visitors * 100) if current.unique_visitors else 0
    period = f"{current.period_start.strftime('%b %d')}–{current.period_end.strftime('%b %d, %Y')}"
    return f"""
      <section class="website-metrics-section" aria-labelledby="website-metrics-title">
        <header><div><h2 id="website-metrics-title">Website analytics</h2><p>{escape(period)} · aggregate tracker data</p></div><a href="/dashboard/metrics?client_id={escape(client_id)}">View details</a></header>
        <div class="website-stat-grid">
          {metric_card('Unique visitors', f'{current.unique_visitors:,}', 'Website visits')}
          {metric_card('Pageviews', f'{current.pageviews:,}', 'Pages viewed')}
          {metric_card('Call clicks', f'{current.call_clicks:,}', 'Phone-link clicks')}
          {metric_card('Form submits', f'{current.form_submits:,}', 'Tracked submissions')}
        </div>
        <footer><span>Call-click conversion: {conversion:.1f}%</span><span>Source: {escape(current.source)}</span></footer>
      </section>
    """


def render_portfolio_rows(database: Session, snapshots: list) -> str:
    if not snapshots:
        return '<p class="overall-empty">No website metrics have been imported for this view.</p>'
    maximum = max(snapshot.unique_visitors for snapshot in snapshots) or 1
    rows = []
    for snapshot in sorted(snapshots, key=lambda item: item.unique_visitors, reverse=True):
        client = database.get(models.Client, snapshot.client_id)
        conversion = snapshot.call_clicks / snapshot.unique_visitors * 100 if snapshot.unique_visitors else 0
        width = snapshot.unique_visitors / maximum * 100
        rows.append(
            f"""
            <article class="overall-client-row">
              <div><a href="/dashboard/metrics?client_id={escape(client.id)}">{escape(client.business_name)}</a><span>{', '.join(snapshot.tracker_sites)}</span></div>
              <div class="visitor-bar"><span style="width:{width:.1f}%"></span></div>
              <strong>{snapshot.unique_visitors:,}</strong><span>{snapshot.pageviews:,}</span><span>{snapshot.call_clicks:,}</span><span>{snapshot.form_submits:,}</span><span>{conversion:.1f}%</span>
            </article>
            """
        )
    return "".join(rows)


@router.get("/dashboard/metrics", response_class=HTMLResponse)
def overall_metrics_dashboard(
    client_id: Optional[str] = None,
    window_days: int = 30,
    synced: int = 0,
    error: str = "",
    database: Session = Depends(get_database),
) -> HTMLResponse:
    if window_days not in {7, 30, 90}:
        window_days = 30
    connections = list(
        database.scalars(
            select(models.WebsiteConnection)
            .where(models.WebsiteConnection.source == "confirmed_vercel_import")
            .order_by(models.WebsiteConnection.project_name)
        )
    )
    clients = [database.get(models.Client, connection.client_id) for connection in connections]
    all_snapshots = latest_portfolio_snapshots(database, window_days)
    selected_client = None
    snapshots = all_snapshots
    if client_id:
        selected_client = require_client(database, client_id)
        snapshots = [item for item in all_snapshots if item.client_id == client_id]

    count = len(snapshots)
    sums = {
        "unique_visitors": sum(item.unique_visitors for item in snapshots),
        "pageviews": sum(item.pageviews for item in snapshots),
        "call_clicks": sum(item.call_clicks for item in snapshots),
        "form_submits": sum(item.form_submits for item in snapshots),
    }
    divisor = count or 1
    if selected_client:
        values = {key: value for key, value in sums.items()}
        label_prefix = ""
        subtitle = f"{selected_client.business_name} · latest {window_days}-day snapshot"
    else:
        values = {key: round(value / divisor, 1) for key, value in sums.items()}
        label_prefix = "Avg. "
        subtitle = f"Portfolio averages across {count} reporting clients"

    options = ['<option value="">All clients</option>'] + [
        f'<option value="{escape(client.id)}"{" selected" if client_id == client.id else ""}>{escape(client.business_name)}</option>'
        for client in sorted(clients, key=lambda item: item.business_name.casefold())
    ]
    notice = '<p class="form-notice success-notice">Website analytics synced. Same-day imports are reused.</p>' if synced else ""
    if error:
        notice = f'<p class="form-notice error-notice">{escape(error)}</p>'
    latest_period = max((item.period_end for item in snapshots), default=None)
    period_text = latest_period.strftime("Through %b %d, %Y") if latest_period else "No snapshot yet"
    window_options = "".join(
        f'<option value="{days}"{" selected" if days == window_days else ""}>{days} days</option>'
        for days in (7, 30, 90)
    )
    page = TEMPLATE_PATH.read_text(encoding="utf-8")
    return HTMLResponse(
        page.replace("{{SUBTITLE}}", escape(subtitle))
        .replace("{{WINDOW_DAYS}}", str(window_days))
        .replace("{{WINDOW_OPTIONS}}", window_options)
        .replace("{{CLIENT_OPTIONS}}", "".join(options))
        .replace("{{NOTICE}}", notice)
        .replace("{{PERIOD}}", escape(period_text))
        .replace("{{VISITORS_LABEL}}", f"{label_prefix}visitors")
        .replace("{{PAGEVIEWS_LABEL}}", f"{label_prefix}pageviews")
        .replace("{{CALLS_LABEL}}", f"{label_prefix}call clicks")
        .replace("{{FORMS_LABEL}}", f"{label_prefix}form submits")
        .replace("{{VISITORS}}", f"{values['unique_visitors']:,.1f}" if not selected_client else f"{values['unique_visitors']:,}")
        .replace("{{PAGEVIEWS}}", f"{values['pageviews']:,.1f}" if not selected_client else f"{values['pageviews']:,}")
        .replace("{{CALLS}}", f"{values['call_clicks']:,.1f}" if not selected_client else f"{values['call_clicks']:,}")
        .replace("{{FORMS}}", f"{values['form_submits']:,.1f}" if not selected_client else f"{values['form_submits']:,}")
        .replace("{{TOTALS}}", f"Portfolio totals: {sums['unique_visitors']:,} visitors · {sums['pageviews']:,} pageviews · {sums['call_clicks']:,} call clicks · {sums['form_submits']:,} forms" if not selected_client else "Selected client values")
        .replace("{{CLIENT_ROWS}}", render_portfolio_rows(database, snapshots))
    )


@router.post("/dashboard/metrics/sync", response_class=RedirectResponse)
async def sync_metrics_form(request: Request, database: Session = Depends(get_database)) -> RedirectResponse:
    encoded = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    values = {key: entries[-1] for key, entries in encoded.items()}
    try:
        window_days = int(values.get("window_days", "30"))
        sync_website_metrics(database, window_days)
    except Exception as error:
        database.rollback()
        return RedirectResponse(url=f"/dashboard/metrics?error={quote(str(error))}", status_code=303)
    return RedirectResponse(url=f"/dashboard/metrics?window_days={window_days}&synced=1", status_code=303)
