"""Read-only, client-scoped provider verification.

Persisted connection rows describe what the owner intended to connect. This
module performs bounded read-only probes against those exact resources and
normalizes provider failures into safe, auditable codes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.audit import record_event
from app.github_service import GitHubAppAdapter, GitHubIntegrationError
from app.google_business_profile_service import (
    GoogleBusinessProfileAdapter,
    GoogleBusinessProfileIntegrationError,
)
from app.google_search_console_service import (
    GoogleSearchConsoleAdapter,
    SearchConsoleIntegrationError,
)
from app.slack_service import SlackIntegrationError, get_slack_adapter
from app.vercel_service import VercelAdapter, VercelIntegrationError


PROVIDER_ERRORS = (
    GitHubIntegrationError,
    GoogleBusinessProfileIntegrationError,
    SearchConsoleIntegrationError,
    SlackIntegrationError,
    VercelIntegrationError,
)


class ProviderVerificationBlocked(RuntimeError):
    """Safe execution-gate failure containing provider codes only."""

    def __init__(self, codes: list[str]) -> None:
        self.codes = codes
        super().__init__("provider_verification_failed:" + ",".join(codes[:8]))


def _result(provider: str, status: str, *, code: str | None = None, retryable: bool = False, detail: str = "") -> dict:
    return {
        "provider": provider,
        "status": status,
        "code": code,
        "retryable": retryable,
        "detail": detail,
        "checked_at": datetime.utcnow().isoformat(),
    }


def _safe_error(error: Exception) -> tuple[str, bool]:
    return str(getattr(error, "code", "provider_probe_failed")), bool(getattr(error, "retryable", False))


def _website_probe(url: str) -> tuple[bool, str]:
    if not url or not url.startswith(("https://", "http://")):
        return False, "website_url_invalid"
    request = Request(url, headers={"User-Agent": "Max-provider-verifier/1.0"}, method="HEAD")
    try:
        with urlopen(request, timeout=15) as response:
            status = int(getattr(response, "status", 200))
    except HTTPError as error:
        # A server that rejects HEAD may still serve the page; retain a clear
        # provider result rather than silently treating it as reachable.
        return False, "website_http_%s" % error.code
    except (URLError, TimeoutError):
        return False, "website_temporarily_unavailable"
    return (200 <= status < 400), ("verified" if 200 <= status < 400 else "website_http_%s" % status)


def verify_client_providers(
    database: Session,
    client_id: str,
    providers: set[str] | None = None,
) -> dict:
    """Probe selected configured providers for one client without writes.

    ``providers`` lets a direct execution gate verify only the resources that
    execution can touch; a full sweep remains the default for launch checks.
    """
    client = database.get(models.Client, client_id)
    if client is None:
        raise ValueError("client_not_found")
    results: list[dict] = []

    def record(provider: str, probe) -> None:
        try:
            result = probe()
            results.append(result if isinstance(result, dict) else _result(provider, "verified"))
        except PROVIDER_ERRORS as error:
            code, retryable = _safe_error(error)
            results.append(_result(provider, "failed", code=code, retryable=retryable, detail="Provider probe failed."))
        except Exception:
            results.append(_result(provider, "failed", code="provider_probe_failed", retryable=True, detail="Provider probe failed."))

    slack = database.scalar(select(models.SlackChannelConnection).where(models.SlackChannelConnection.client_id == client_id))
    if slack is not None and (providers is None or "slack" in providers):
        def probe_slack() -> dict:
            adapter = get_slack_adapter()
            workspace = adapter.verify_workspace()
            if workspace.id != slack.workspace_id:
                return _result("slack", "failed", code="slack_workspace_mismatch", detail="Connected workspace does not match the saved client boundary.")
            channel = adapter.get_channel(slack.channel_id)
            if channel.id != slack.channel_id or channel.is_archived:
                return _result("slack", "failed", code="slack_channel_unavailable", detail="Saved client channel is archived or unavailable.")
            return _result("slack", "verified", detail="Workspace and client channel verified.")
        record("slack", probe_slack)
        result = results[-1]
        slack.last_verified_at = datetime.utcnow()
        slack.last_error = result.get("code") if result["status"] == "failed" else None
        slack.connection_status = "error" if result["status"] == "failed" else "connected"

    website = database.scalar(select(models.WebsiteConnection).where(models.WebsiteConnection.client_id == client_id))
    if website is not None and (providers is None or "website" in providers):
        def probe_website() -> dict:
            reachable, code = _website_probe(website.production_url)
            return _result(
                "website",
                "verified" if reachable else "failed",
                code=None if reachable else code,
                detail="Production URL responded successfully." if reachable else "Production URL could not be verified.",
            )
        record("website", probe_website)
        result = results[-1]
        website.connection_status = "error" if result["status"] == "failed" else "connected"

    github = database.scalar(select(models.GitHubRepositoryConnection).where(models.GitHubRepositoryConnection.client_id == client_id))
    if github is not None and (providers is None or "github" in providers):
        def probe_github() -> dict:
            repository = GitHubAppAdapter().get_repository(github.owner, github.repository_name)
            if repository.owner.casefold() != github.owner.casefold() or repository.name.casefold() != github.repository_name.casefold():
                return _result("github", "failed", code="github_repository_mismatch", detail="Provider returned a different repository.")
            return _result("github", "verified", detail="Scoped repository identity verified.")
        record("github", probe_github)
        result = results[-1]
        github.last_checked_at = datetime.utcnow()
        github.last_verified_at = github.last_checked_at if result["status"] == "verified" else github.last_verified_at
        github.connection_status = "error" if result["status"] == "failed" else "connected"

    search_console = database.scalar(select(models.SearchConsoleConnection).where(models.SearchConsoleConnection.client_id == client_id))
    if search_console is not None and (providers is None or "search_console" in providers):
        def probe_search_console() -> dict:
            end = date.today()
            start = end - timedelta(days=7)
            GoogleSearchConsoleAdapter().read_metrics(search_console.property_url, start.isoformat(), end.isoformat())
            return _result("search_console", "verified", detail="Search Console property accepted a read-only metrics query.")
        record("search_console", probe_search_console)
        result = results[-1]
        search_console.last_checked_at = datetime.utcnow()
        search_console.last_error = result.get("code") if result["status"] == "failed" else None
        search_console.connection_status = "error" if result["status"] == "failed" else "connected"
        if result["status"] == "verified":
            search_console.last_successful_sync_at = datetime.utcnow()

    gbp = database.scalar(select(models.GoogleBusinessProfileConnection).where(models.GoogleBusinessProfileConnection.client_id == client_id))
    if gbp is not None and (providers is None or "google_business_profile" in providers):
        record("google_business_profile", lambda: (_result("google_business_profile", "verified", detail="GBP location inspection succeeded.") if GoogleBusinessProfileAdapter().inspect_location(gbp.account_id, gbp.location_id) else _result("google_business_profile", "failed", code="gbp_invalid_response", detail="GBP inspection returned no result.")))
        result = results[-1]
        gbp.last_checked_at = datetime.utcnow()
        gbp.connection_status = "error" if result["status"] == "failed" else "connected"

    for result in results:
        record_event(
            database,
            "client_provider_verification",
            client_id=client_id,
            record_type="provider",
            record_id=client_id,
            details={
                "provider": result["provider"],
                "status": result["status"],
                "code": result.get("code"),
                "retryable": result.get("retryable", False),
            },
        )
    database.flush()
    failed = sum(result["status"] == "failed" for result in results)
    return {
        "client": {"id": client.id, "business_name": client.business_name},
        "status": "verified" if failed == 0 else "failed",
        "summary": {"verified": len(results) - failed, "failed": failed, "probed": len(results)},
        "results": results,
        "generated_at": datetime.utcnow().isoformat(),
    }


def require_provider_health(
    database: Session,
    client_id: str,
    providers: set[str],
) -> dict:
    """Return a relevant probe or raise with only safe provider codes."""
    result = verify_client_providers(database, client_id, providers)
    failed_codes = [
        str(item.get("code") or "provider_probe_failed")
        for item in result["results"]
        if item.get("status") == "failed"
    ]
    if failed_codes:
        raise ProviderVerificationBlocked(failed_codes)
    return result


def sweep_active_clients(database: Session) -> dict:
    """Probe every active client and return only safe provider summaries."""
    client_ids = list(
        database.scalars(
            select(models.Client.id)
            .where(models.Client.archived_at.is_(None), models.Client.status != "archived")
            .order_by(models.Client.id)
        )
    )
    reports = []
    failed = False
    for client_id in client_ids:
        result = verify_client_providers(database, client_id)
        failed = failed or result["status"] == "failed"
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
    return {"status": "failed" if failed else "verified", "clients": reports}
