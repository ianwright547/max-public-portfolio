"""Client-bound, read-only Google Search Console connections and imports."""

from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_database
from app.google_search_console_service import GoogleSearchConsoleAdapter, SearchConsoleIntegrationError
from app.routes.metrics import add_metric_snapshot

router = APIRouter(tags=["search console"])


def _hostname(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").lower().rstrip(".")


def client_domains(database: Session, client_id: str) -> set[str]:
    """Collect only domains already stored under this exact client."""
    domains: set[str] = set()
    website = database.scalar(
        select(models.WebsiteConnection).where(models.WebsiteConnection.client_id == client_id)
    )
    if website is not None:
        host = _hostname(website.production_url)
        if host:
            domains.add(host)
    for intake_domain in database.scalars(
        select(models.Intake.domain).where(models.Intake.client_id == client_id)
    ):
        host = _hostname(intake_domain)
        if host:
            domains.add(host)
    return domains


def property_matches_client(property_url: str, domains: set[str]) -> bool:
    """Allow exact domains, plus the normal www-to-root Search Console match."""
    value = property_url.strip().rstrip("/").lower()
    if value.startswith("sc-domain:"):
        property_domain = value.removeprefix("sc-domain:").rstrip(".")
        return property_domain in domains or f"www.{property_domain}" in domains
    property_domain = _hostname(value)
    return bool(property_domain and property_domain in domains)


def property_format_is_valid(property_url: str) -> bool:
    """Search Console accepts domain properties or trailing-slash URL-prefix properties."""
    value = property_url.strip()
    if value.lower().startswith("sc-domain:"):
        return bool(_hostname(value.removeprefix("sc-domain:")))
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and value.endswith("/")


def require_client(database: Session, client_id: str) -> models.Client:
    client = database.get(models.Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _record_integration_status(
    database: Session,
    client_id: str,
    status_value: str,
    issues: list[str],
    checked_at: datetime,
) -> None:
    """Mirror connector failures into report-visible integration evidence."""
    integration = database.scalar(
        select(models.IntegrationConnection).where(
            models.IntegrationConnection.client_id == client_id,
            models.IntegrationConnection.integration_name == "Google Search Console",
            models.IntegrationConnection.data_source_type == "live_api",
        )
    )
    if integration is None:
        integration = models.IntegrationConnection(
            client_id=client_id,
            integration_name="Google Search Console",
            connection_status=status_value,
            data_source_type="live_api",
            issues=issues,
        )
        database.add(integration)
    integration.connection_status = status_value
    integration.last_checked_at = checked_at
    integration.issues = issues


@router.post(
    "/clients/{client_id}/search-console",
    response_model=schemas.SearchConsoleConnectionRead,
    status_code=status.HTTP_201_CREATED,
)
def connect_search_console(
    client_id: str,
    connection: schemas.SearchConsoleConnectionCreate,
    database: Session = Depends(get_database),
) -> models.SearchConsoleConnection:
    """Save a property only after it matches the client's saved website domain."""
    require_client(database, client_id)
    if not property_format_is_valid(connection.property_url):
        raise HTTPException(
            status_code=422,
            detail="Search Console property must use sc-domain:example.com or https://example.com/",
        )
    domains = client_domains(database, client_id)
    if not domains:
        raise HTTPException(status_code=409, detail="Client needs a saved website or onboarding domain first")
    if not property_matches_client(connection.property_url, domains):
        raise HTTPException(status_code=409, detail="Search Console property does not match this client domain")
    existing = database.scalar(
        select(models.SearchConsoleConnection).where(
            (models.SearchConsoleConnection.client_id == client_id)
            | (models.SearchConsoleConnection.property_url == connection.property_url)
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Client or Search Console property is already linked")
    record = models.SearchConsoleConnection(client_id=client_id, property_url=connection.property_url)
    database.add(record)
    database.commit()
    database.refresh(record)
    return record


@router.get(
    "/clients/{client_id}/search-console",
    response_model=schemas.SearchConsoleConnectionRead,
)
def read_search_console(
    client_id: str, database: Session = Depends(get_database)
) -> models.SearchConsoleConnection:
    require_client(database, client_id)
    record = database.scalar(
        select(models.SearchConsoleConnection).where(models.SearchConsoleConnection.client_id == client_id)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Search Console connection not found")
    return record


@router.post(
    "/clients/{client_id}/search-console/sync",
    response_model=list[schemas.MetricRead],
)
def sync_search_console(
    client_id: str,
    request: schemas.SearchConsoleSyncRequest,
    database: Session = Depends(get_database),
) -> list[models.MetricSnapshot]:
    """Read aggregate clicks/impressions and preserve them as live historical metrics."""
    require_client(database, client_id)
    if request.end_date < request.start_date:
        raise HTTPException(status_code=422, detail="end_date must be on or after start_date")
    connection = read_search_console(client_id, database)
    domains = client_domains(database, client_id)
    if not property_matches_client(connection.property_url, domains):
        connection.connection_status = "mismatch"
        connection.last_error = "search_console_client_domain_mismatch"
        connection.last_checked_at = datetime.utcnow()
        _record_integration_status(
            database,
            client_id,
            "mismatch",
            ["search_console_client_domain_mismatch"],
            connection.last_checked_at,
        )
        database.commit()
        raise HTTPException(status_code=409, detail="Search Console property no longer matches this client domain")

    checked_at = datetime.utcnow()
    try:
        adapter = GoogleSearchConsoleAdapter()
        if hasattr(adapter, "read_report"):
            report = adapter.read_report(
                connection.property_url,
                request.start_date.isoformat(),
                request.end_date.isoformat(),
            )
            values = report.metrics
        else:  # pragma: no cover - compatibility for minimal test adapters
            from app.google_search_console_service import SearchConsoleReport

            values = adapter.read_metrics(
                connection.property_url,
                request.start_date.isoformat(),
                request.end_date.isoformat(),
            )
            report = SearchConsoleReport(metrics=values)
    except SearchConsoleIntegrationError as error:
        connection.connection_status = "error"
        connection.last_checked_at = checked_at
        connection.last_error = error.code
        _record_integration_status(database, client_id, "error", [error.code], checked_at)
        database.commit()
        raise HTTPException(status_code=503 if error.retryable else 502, detail=error.code) from error

    if not values.has_data:
        _record_integration_status(
            database,
            client_id,
            "not_enough_data",
            ["No usable Search Console data exists for the requested date range."],
            checked_at,
        )
        connection.connection_status = "not_enough_data"
        connection.last_checked_at = checked_at
        connection.last_error = None
        connection.last_query_rows = []
        connection.last_page_rows = []
        connection.last_query_start_date = request.start_date
        connection.last_query_end_date = request.end_date
        database.commit()
        return []

    period = request.end_date.strftime("%Y-%m")
    try:
        snapshots = [
            add_metric_snapshot(
                database,
                client_id,
                "search_clicks",
                values.clicks,
                period,
                "live_api",
                request.mark_as_baseline,
            ),
            add_metric_snapshot(
                database,
                client_id,
                "impressions",
                values.impressions,
                period,
                "live_api",
                request.mark_as_baseline,
            ),
        ]
    except HTTPException:
        database.rollback()
        raise
    _record_integration_status(database, client_id, "connected", [], checked_at)
    connection.connection_status = "connected"
    connection.last_checked_at = checked_at
    connection.last_successful_sync_at = checked_at
    connection.last_error = None
    connection.last_query_rows = list(report.query_rows)
    connection.last_page_rows = list(report.page_rows)
    connection.last_query_start_date = request.start_date
    connection.last_query_end_date = request.end_date
    database.commit()
    for snapshot in snapshots:
        database.refresh(snapshot)
    return snapshots
