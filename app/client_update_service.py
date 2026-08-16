"""Evidence-backed simple summaries and fresh in-depth client audits."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
import hashlib
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.error import URLError

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.google_business_profile_service import GoogleBusinessProfileIntegrationError
from app.google_search_console_service import SearchConsoleIntegrationError


MAX_PORTFOLIO_CLIENTS = 50
MAX_SLACK_REPORT_CHARS = 35_000
MAX_INTERNAL_LINK_CHECKS = 20
_SENSITIVE_FAILURE_TEXT = re.compile(
    r"(?i)(api[_ -]?key|access[_ -]?token|authorization|password|secret|credential|traceback|stack trace|exception:|\.env|private key)"
)


@dataclass
class WebsiteEvidence:
    url: str | None = None
    final_url: str | None = None
    status_code: int | None = None
    title: str | None = None
    meta_description: str | None = None
    h1_count: int = 0
    canonical: str | None = None
    has_viewport: bool = False
    has_local_business_schema: bool = False
    has_phone_link: bool = False
    has_contact_form: bool = False
    internal_link_count: int = 0
    checked_internal_link_count: int = 0
    broken_internal_link_count: int = 0
    image_count: int = 0
    images_missing_alt: int = 0
    audited_page_count: int = 0
    pages_missing_title: int = 0
    pages_missing_description: int = 0
    pages_without_one_h1: int = 0
    duplicate_title_count: int = 0
    robots_status: int | None = None
    sitemap_status: int | None = None
    blocker_code: str | None = None
    blocker_detail: str | None = None


@dataclass
class ClientUpdate:
    client_id: str
    business_name: str
    mode: str
    status: str
    facts: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)
    plan_30: list[str] = field(default_factory=list)
    plan_60: list[str] = field(default_factory=list)
    plan_90: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    structured_evidence: dict[str, Any] = field(default_factory=dict)
    persisted_finding_ids: list[str] = field(default_factory=list)


@dataclass
class PortfolioUpdate:
    mode: str
    clients: list[ClientUpdate]
    portfolio_notes: list[str] = field(default_factory=list)


class _PageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.in_title = False
        self.meta_description: str | None = None
        self.h1_count = 0
        self.canonical: str | None = None
        self.has_viewport = False
        self.has_local_business_schema = False
        self.in_json_ld = False
        self.json_ld_parts: list[str] = []
        self.has_phone_link = False
        self.has_contact_form = False
        self.internal_links: set[str] = set()
        self.image_count = 0
        self.images_missing_alt = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): (value or "") for key, value in attrs}
        tag = tag.casefold()
        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            name = values.get("name", "").casefold()
            if name == "description" and values.get("content"):
                self.meta_description = values["content"].strip()
            if name == "viewport":
                self.has_viewport = True
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "link" and "canonical" in values.get("rel", "").casefold():
            self.canonical = values.get("href") or None
        elif tag == "script" and values.get("type", "").casefold() == "application/ld+json":
            self.in_json_ld = True
        elif tag == "a":
            href = values.get("href", "").strip()
            if href.casefold().startswith("tel:"):
                self.has_phone_link = True
            absolute = urljoin(self.base_url, href)
            if href and urlparse(absolute).netloc.casefold() == urlparse(self.base_url).netloc.casefold():
                self.internal_links.add(absolute.split("#", 1)[0])
        elif tag == "form":
            self.has_contact_form = True
        elif tag == "img":
            self.image_count += 1
            if not values.get("alt", "").strip():
                self.images_missing_alt += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self.in_title = False
        if tag.casefold() == "script" and self.in_json_ld:
            value = " ".join(self.json_ld_parts).casefold()
            self.has_local_business_schema = any(
                schema in value
                for schema in ("localbusiness", "autorepair", "automotivebusiness")
            )
            self.in_json_ld = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self.in_json_ld:
            self.json_ld_parts.append(data)

    @property
    def title(self) -> str | None:
        value = " ".join(" ".join(self.title_parts).split())
        return value or None


def _normalized_website_url(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    url = value.strip()
    if not urlparse(url).scheme:
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return url


def _require_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("website_url_invalid")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except socket.gaierror as error:
        raise ValueError("website_dns_failed") from error
    if not addresses:
        raise ValueError("website_dns_failed")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("website_address_not_public")


def _fetch_public(client: httpx.Client, url: str, *, max_redirects: int = 4) -> httpx.Response:
    current = url
    for _ in range(max_redirects + 1):
        _require_public_url(current)
        response = client.get(current, follow_redirects=False)
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        current = urljoin(current, location)
    raise ValueError("website_redirect_limit")


def probe_website(url: str | None) -> WebsiteEvidence:
    normalized = _normalized_website_url(url)
    if normalized is None:
        return WebsiteEvidence(
            blocker_code="website_url_missing",
            blocker_detail="No valid public website URL is saved for this client.",
        )
    evidence = WebsiteEvidence(url=normalized)
    headers = {"User-Agent": "MaxClientAudit/1.0 (+website health and SEO audit)"}
    try:
        with httpx.Client(headers=headers, timeout=8.0) as client:
            response = _fetch_public(client, normalized)
            evidence.final_url = str(response.url)
            evidence.status_code = response.status_code
            if response.status_code >= 400:
                evidence.blocker_code = f"website_http_{response.status_code}"
                evidence.blocker_detail = f"The website returned HTTP {response.status_code}."
                return evidence
            content_type = response.headers.get("content-type", "").casefold()
            if "html" not in content_type:
                evidence.blocker_code = "website_not_html"
                evidence.blocker_detail = f"The website returned `{content_type or 'an unknown content type'}` instead of HTML."
                return evidence
            parser = _PageParser(evidence.final_url)
            parser.feed(response.text[:2_000_000])
            evidence.title = parser.title
            evidence.meta_description = parser.meta_description
            evidence.h1_count = parser.h1_count
            evidence.canonical = parser.canonical
            evidence.has_viewport = parser.has_viewport
            evidence.has_local_business_schema = parser.has_local_business_schema
            evidence.has_phone_link = parser.has_phone_link
            evidence.has_contact_form = parser.has_contact_form
            evidence.internal_link_count = len(parser.internal_links)
            evidence.image_count = parser.image_count
            evidence.images_missing_alt = parser.images_missing_alt
            evidence.audited_page_count = 1
            evidence.pages_missing_title = 0 if parser.title else 1
            evidence.pages_missing_description = 0 if parser.meta_description else 1
            evidence.pages_without_one_h1 = 0 if parser.h1_count == 1 else 1
            titles = [parser.title.casefold()] if parser.title else []
            links_to_check = set(parser.internal_links)
            homepage = evidence.final_url.rstrip("/")
            candidate_pages = [
                page
                for page in sorted(parser.internal_links)
                if page.rstrip("/") != homepage and urlparse(page).scheme in {"http", "https"}
            ][:5]
            for page_url in candidate_pages:
                try:
                    page_response = _fetch_public(client, page_url)
                    if page_response.status_code >= 400 or "html" not in page_response.headers.get("content-type", "").casefold():
                        continue
                    page_parser = _PageParser(str(page_response.url))
                    page_parser.feed(page_response.text[:2_000_000])
                    links_to_check.update(page_parser.internal_links)
                    evidence.audited_page_count += 1
                    evidence.pages_missing_title += 0 if page_parser.title else 1
                    evidence.pages_missing_description += 0 if page_parser.meta_description else 1
                    evidence.pages_without_one_h1 += 0 if page_parser.h1_count == 1 else 1
                    if page_parser.title:
                        title = page_parser.title.casefold()
                        if title in titles:
                            evidence.duplicate_title_count += 1
                        titles.append(title)
                except (httpx.HTTPError, ValueError):
                    continue
            evidence.internal_link_count = len(links_to_check)
            for link_url in sorted(links_to_check)[:MAX_INTERNAL_LINK_CHECKS]:
                if link_url.rstrip("/") == homepage:
                    continue
                evidence.checked_internal_link_count += 1
                try:
                    link_response = _fetch_public(client, link_url)
                    if link_response.status_code >= 400:
                        evidence.broken_internal_link_count += 1
                except (httpx.HTTPError, ValueError):
                    evidence.broken_internal_link_count += 1
            origin = f"{urlparse(evidence.final_url).scheme}://{urlparse(evidence.final_url).netloc}"
            for path, attribute in (("/robots.txt", "robots_status"), ("/sitemap.xml", "sitemap_status")):
                try:
                    setattr(evidence, attribute, _fetch_public(client, origin + path).status_code)
                except (httpx.HTTPError, ValueError):
                    setattr(evidence, attribute, None)
    except ValueError as error:
        evidence.blocker_code = str(error)
        evidence.blocker_detail = _website_error_solution(str(error))
    except httpx.TimeoutException:
        evidence.blocker_code = "website_timeout"
        evidence.blocker_detail = "The website did not respond within 8 seconds."
    except httpx.HTTPError as error:
        evidence.blocker_code = "website_request_failed"
        evidence.blocker_detail = f"The public website request failed ({error.__class__.__name__})."
    return evidence


def _website_error_solution(code: str) -> str:
    return {
        "website_dns_failed": "The domain did not resolve in public DNS. Confirm the domain, DNS records, and hosting assignment.",
        "website_address_not_public": "The saved URL resolves to a private or reserved address and cannot be audited safely. Provide the public production URL.",
        "website_redirect_limit": "The website exceeded the safe redirect limit. Repair the redirect chain or provide the final production URL.",
        "website_url_invalid": "The saved website URL is invalid. Save a valid HTTP or HTTPS production URL.",
    }.get(code, f"The website could not be checked (`{code}`). Confirm the production URL and public access.")


def _website_url(database: Session, client: models.Client) -> str | None:
    connection = database.scalar(
        select(models.WebsiteConnection).where(models.WebsiteConnection.client_id == client.id)
    )
    if connection is not None and connection.production_url:
        return connection.production_url
    intake = database.scalar(
        select(models.Intake)
        .where(models.Intake.client_id == client.id)
        .order_by(models.Intake.submitted_at.desc(), models.Intake.id.desc())
    )
    return intake.domain if intake is not None else None


def _latest_task_counts(database: Session, client_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    tasks = list(database.scalars(select(models.Task).where(models.Task.client_id == client_id)))
    for task in tasks:
        counts[task.status] = counts.get(task.status, 0) + 1
    return counts


def _simple_client_update(database: Session, client: models.Client) -> ClientUpdate:
    update = ClientUpdate(client.id, client.business_name, "simple", client.status)
    counts = _latest_task_counts(database, client.id)
    update.facts.append(f"Client status: {client.status}.")
    if counts:
        update.facts.append("Tasks: " + ", ".join(f"{count} {status}" for status, count in sorted(counts.items())) + ".")
    unread = list(
        database.scalars(
            select(models.Notification).where(
                models.Notification.client_id == client.id,
                models.Notification.is_read.is_(False),
            )
        )
    )
    if unread:
        update.facts.append(f"Unread alerts: {len(unread)}.")
    update.sources.append("Saved Max records (no live refresh requested)")
    return update


def _append_website_findings(update: ClientUpdate, evidence: WebsiteEvidence) -> None:
    # Keep the raw structured result even when the page cannot be reached so
    # the owner report can distinguish a missing URL from an HTTP/DNS blocker.
    update.structured_evidence["website"] = asdict(evidence)
    if evidence.blocker_code:
        update.blockers.append(f"Website: {evidence.blocker_detail}")
        update.needs.append("Confirm the public production URL and remove any login, firewall, DNS, or hosting block preventing public access.")
        update.plan_30.append("Restore public website access, then rerun the in-depth audit before making SEO recommendations from page content.")
        return
    update.facts.append(f"Website reachable at {evidence.final_url} (HTTP {evidence.status_code}).")
    update.facts.append(f"Fresh technical crawl inspected {evidence.audited_page_count} public HTML page(s).")
    update.sources.append(f"Fresh public website crawl: {evidence.final_url}")
    if not evidence.title:
        update.gaps.append("Homepage title tag is missing.")
        update.plan_30.append("Write a unique homepage title with the primary service, business name, and main market.")
    elif len(evidence.title) < 20 or len(evidence.title) > 65:
        update.gaps.append(f"Homepage title length is weak ({len(evidence.title)} characters).")
        update.plan_30.append("Rewrite the homepage title to clearly target the primary service and location in roughly 30–60 characters.")
    if not evidence.meta_description:
        update.gaps.append("Homepage meta description is missing.")
        update.plan_30.append("Add a specific homepage meta description with service, market, differentiator, and call to action.")
    if evidence.h1_count != 1:
        update.gaps.append(f"Homepage has {evidence.h1_count} H1 headings; one clear primary H1 is recommended.")
        update.plan_30.append("Use one descriptive homepage H1 aligned with the primary local search intent.")
    if not evidence.canonical:
        update.gaps.append("Homepage canonical tag is missing.")
        update.plan_30.append("Add a self-referencing canonical tag and verify all important pages canonicalize correctly.")
    if not evidence.has_viewport:
        update.gaps.append("Mobile viewport metadata is missing.")
        update.plan_30.append("Add responsive viewport metadata and verify the core conversion path on mobile.")
    if evidence.robots_status != 200:
        update.gaps.append("robots.txt was not verified at the standard location.")
        update.plan_30.append("Publish and review robots.txt so important service and location pages remain crawlable.")
    if evidence.sitemap_status != 200:
        update.gaps.append("sitemap.xml was not verified at the standard location.")
        update.plan_30.append("Generate an XML sitemap, include canonical indexable pages, and submit it in Search Console.")
    if not evidence.has_local_business_schema:
        update.gaps.append("No JSON-LD structured data was detected on the homepage.")
        update.plan_30.append("Add accurate LocalBusiness/AutoRepair structured data using verified business facts only.")
    if not evidence.has_phone_link and not evidence.has_contact_form:
        update.gaps.append("No phone link or contact form was detected on the homepage.")
        update.plan_30.append("Add a prominent mobile phone CTA or tracked appointment/contact form.")
    if evidence.images_missing_alt:
        update.gaps.append(f"{evidence.images_missing_alt} of {evidence.image_count} homepage images are missing useful alt text.")
        update.plan_60.append("Add concise, factual alt text to meaningful images and leave decorative images empty.")
    if evidence.internal_link_count < 3:
        update.gaps.append(f"Only {evidence.internal_link_count} internal homepage links were detected.")
        update.plan_60.append("Build descriptive internal links from the homepage to priority service, location, about, and contact pages.")
    if evidence.broken_internal_link_count:
        update.gaps.append(
            f"{evidence.broken_internal_link_count} of {evidence.checked_internal_link_count} checked internal links returned an error or could not be reached."
        )
        update.plan_30.append(
            "Repair or redirect the broken internal links, then recrawl the affected pages and confirm the destination returns a successful response."
        )
    if evidence.pages_missing_title:
        update.gaps.append(f"{evidence.pages_missing_title} of {evidence.audited_page_count} audited pages are missing title tags.")
        update.plan_30.append("Add a unique intent-matched title to every audited indexable page missing one.")
    if evidence.pages_missing_description:
        update.gaps.append(f"{evidence.pages_missing_description} of {evidence.audited_page_count} audited pages are missing meta descriptions.")
        update.plan_60.append("Write unique descriptions for priority service and location pages using accurate offers and calls to action.")
    if evidence.pages_without_one_h1:
        update.gaps.append(f"{evidence.pages_without_one_h1} of {evidence.audited_page_count} audited pages do not have exactly one H1.")
        update.plan_30.append("Give each audited page one clear H1 matching that page’s primary purpose.")
    if evidence.duplicate_title_count:
        update.gaps.append(f"{evidence.duplicate_title_count} audited pages reuse another page’s title.")
        update.plan_60.append("Replace duplicate titles so each service or location page targets a distinct search intent.")


def _refresh_search_console(database: Session, client: models.Client, update: ClientUpdate) -> None:
    connection = database.scalar(
        select(models.SearchConsoleConnection).where(models.SearchConsoleConnection.client_id == client.id)
    )
    if connection is None:
        update.blockers.append("Search Console: no property is connected, so rankings, impressions, and clicks could not be verified.")
        update.needs.append("Connect the exact Search Console domain or URL-prefix property for this client and grant the configured Google account read access.")
        return
    from app.routes.search_console import sync_search_console

    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=89)
    try:
        snapshots = sync_search_console(
            client.id,
            schemas.SearchConsoleSyncRequest(start_date=start, end_date=end, mark_as_baseline=False),
            database,
        )
    except (HTTPException, ValueError, URLError, TimeoutError) as error:
        detail = getattr(error, "detail", None) or str(error)
        update.blockers.append(f"Search Console: refresh failed (`{detail}`).")
        if detail == "search_console_authorization_failed":
            update.needs.append("Reconnect Google OAuth or grant the configured Google account access to the saved Search Console property.")
        elif detail == "search_console_property_not_found":
            update.needs.append("Correct the saved Search Console property and verify it exists in the connected Google account.")
        else:
            update.needs.append("Verify the Search Console property mapping and Google OAuth configuration, then rerun the audit.")
        return
    if not snapshots:
        update.gaps.append("Search Console returned no usable data for the last 90 days.")
        update.plan_30.append("Verify indexing and sitemap submission, then inspect Search Console coverage and query data after collection resumes.")
        update.sources.append(f"Fresh Search Console query: {connection.property_url} ({start} to {end}, no rows)")
        return
    values = {snapshot.metric_name: snapshot.value for snapshot in snapshots}
    update.facts.append(
        f"Search Console (last 90 days): {int(values.get('search_clicks', 0)):,} clicks and {int(values.get('impressions', 0)):,} impressions."
    )
    update.sources.append(f"Fresh Search Console API: {connection.property_url} ({start} to {end})")
    query_rows = list(connection.last_query_rows or [])
    page_rows = list(connection.last_page_rows or [])
    update.structured_evidence["search_console"] = {
        "property_url": connection.property_url,
        "start_date": connection.last_query_start_date.isoformat() if connection.last_query_start_date else start.isoformat(),
        "end_date": connection.last_query_end_date.isoformat() if connection.last_query_end_date else end.isoformat(),
        "query_rows": query_rows,
        "page_rows": page_rows,
    }
    zero_click_queries = [
        row for row in query_rows
        if isinstance(row, dict) and float(row.get("impressions", 0) or 0) >= 10 and float(row.get("clicks", 0) or 0) == 0
    ]
    if zero_click_queries:
        examples = ", ".join(str(row.get("key")) for row in zero_click_queries[:3])
        update.gaps.append(
            f"{len(zero_click_queries)} Search Console quer{'y' if len(zero_click_queries) == 1 else 'ies'} had at least 10 impressions but zero clicks ({examples})."
        )
        update.plan_30.append(
            "Review the pages and titles earning Search Console impressions without clicks, then test clearer intent-matched titles and descriptions without claiming a guaranteed ranking or traffic lift."
        )
    if page_rows:
        update.facts.append(f"Search Console returned {len(page_rows)} top page opportunities for the same period.")
    if float(values.get("impressions", 0)) > 0 and float(values.get("search_clicks", 0)) == 0:
        update.plan_30.append("Improve titles and descriptions on pages already receiving impressions to earn the first organic clicks.")


def _append_analytics(database: Session, client: models.Client, update: ClientUpdate) -> None:
    snapshot = database.scalar(
        select(models.WebsiteMetricSnapshot)
        .where(models.WebsiteMetricSnapshot.client_id == client.id)
        .order_by(models.WebsiteMetricSnapshot.period_end.desc(), models.WebsiteMetricSnapshot.id.desc())
    )
    if snapshot is None:
        update.blockers.append("Website analytics: no current tracker snapshot is available.")
        update.needs.append("Install or map the agency website tracker for this production domain, then rerun the 30-day analytics sync.")
        return
    update.facts.append(
        f"Website analytics ({snapshot.period_start} to {snapshot.period_end}): "
        f"{snapshot.unique_visitors:,} visitors, {snapshot.call_clicks:,} call clicks, {snapshot.form_submits:,} forms."
    )
    update.sources.append(f"Website analytics snapshot refreshed through {snapshot.period_end}")
    if snapshot.unique_visitors and snapshot.call_clicks + snapshot.form_submits == 0:
        update.plan_30.append("Audit CTA visibility and conversion tracking because traffic produced no recorded calls or forms.")


def _append_gbp(database: Session, client: models.Client, update: ClientUpdate) -> None:
    connection = database.scalar(
        select(models.GoogleBusinessProfileConnection).where(
            models.GoogleBusinessProfileConnection.client_id == client.id
        )
    )
    if connection is None:
        update.blockers.append("Google Business Profile: no verified profile connection is saved.")
        update.needs.append("Connect the correct Google Business Profile account and location for this client.")
    else:
        update.facts.append(f"Google Business Profile location is mapped as `{connection.location_name}` ({connection.connection_status}).")
        from app.google_business_profile_service import GoogleBusinessProfileAdapter, GoogleBusinessProfileIntegrationError

        try:
            inspection = GoogleBusinessProfileAdapter().inspect_location(
                connection.account_id, connection.location_id
            )
        except GoogleBusinessProfileIntegrationError as error:
            update.blockers.append(
                f"Google Business Profile: live inspection failed (`{error}`)."
            )
            update.needs.append(
                "Reconnect Google OAuth with Business Profile read access and verify the saved account/location mapping, then rerun the audit."
            )
        else:
            evidence = inspection.as_dict()
            update.structured_evidence["google_business_profile"] = evidence
            update.sources.append(
                f"Live Google Business Profile inspection: {connection.location_id}"
            )
            update.facts.append(
                "GBP inspection verified "
                f"{len(inspection.categories)} categor{'y' if len(inspection.categories) == 1 else 'ies'}, "
                f"{'hours' if inspection.hours_present else 'no regular hours'}, and "
                f"{inspection.review_count if inspection.review_count is not None else 'unknown'} reviews."
            )
            if not inspection.categories:
                update.gaps.append("Google Business Profile has no readable category data.")
                update.plan_60.append("Choose and verify the most accurate primary GBP category from the client's real services.")
            if not inspection.hours_present:
                update.gaps.append("Google Business Profile regular hours were not returned.")
                update.plan_60.append("Confirm and publish accurate regular hours after owner approval.")
            if inspection.review_count == 0:
                update.gaps.append("Google Business Profile has no reviews recorded in the inspected response.")
                update.plan_60.append("Create an owner-approved review request and response process; never manufacture reviews.")
            update.plan_60.append("Review GBP inspection evidence and correct only approved categories, hours, services, and profile facts.")


def _in_depth_client_update(database: Session, client: models.Client) -> ClientUpdate:
    update = ClientUpdate(client.id, client.business_name, "in_depth", client.status)
    update.facts.append(f"Client status: {client.status}.")
    evidence = probe_website(_website_url(database, client))
    _append_website_findings(update, evidence)
    _refresh_search_console(database, client, update)
    _append_analytics(database, client, update)
    _append_gbp(database, client, update)
    update.plan_60.append("Create or improve evidence-rich service pages and location coverage based on real customer demand and Search Console queries.")
    update.plan_90.append("Publish supporting local content, strengthen internal links, and compare 90-day Search Console and conversion performance against this audit.")
    update.plan_90.append("Review completed work, keep only actions tied to measurable impressions, clicks, calls, forms, bookings, or qualified leads, and plan the next quarter.")
    return update


def _persist_audit_findings(database: Session, update: ClientUpdate) -> None:
    """Materialize fresh audit gaps as durable, client-scoped findings.

    The audit remains advisory: this creates open findings only. It never creates
    or approves execution tasks, and a later verification is still required to
    resolve one.
    """
    candidates = [("gap", value) for value in update.gaps] + [("blocker", value) for value in update.blockers]
    actions = list(update.plan_30) + list(update.plan_60) + list(update.plan_90)
    for kind, detail in candidates:
        normalized = " ".join(detail.casefold().split())
        rule_key = f"in_depth_audit:{hashlib.sha256(normalized.encode()).hexdigest()[:32]}"
        finding = database.scalar(
            select(models.Finding).where(
                models.Finding.client_id == update.client_id,
                models.Finding.rule_key == rule_key,
                models.Finding.status == "open",
            )
        )
        recommended = next((item for item in actions if item), "Review the evidence and propose a scoped corrective task.")
        evidence = {
            "source": "in_depth_client_audit",
            "mode": update.mode,
            "detail": detail,
            "sources": list(update.sources),
        }
        if finding is None:
            finding = models.Finding(
                client_id=update.client_id,
                rule_key=rule_key,
                title=detail[:200],
                explanation=detail[:1000],
                evidence=evidence,
                source="in_depth_audit",
                severity="high" if kind == "blocker" else "warning",
                confidence="medium",
                recommended_action=recommended[:1000],
                status="open",
            )
            database.add(finding)
            database.flush()
        else:
            finding.explanation = detail[:1000]
            finding.evidence = evidence
            finding.recommended_action = recommended[:1000]
            finding.last_seen_at = datetime.utcnow()
            finding.occurrence_count += 1
        update.persisted_finding_ids.append(finding.id)


def _blocked_client_update(client: models.Client, error: Exception) -> ClientUpdate:
    """Return a truthful partial report when a provider boundary fails unexpectedly."""
    detail = _safe_failure_detail(error)
    update = ClientUpdate(client.id, client.business_name, "in_depth", client.status)
    update.blockers.append(f"The in-depth audit stopped at a provider boundary (`{detail}`).")
    update.needs.append("Confirm provider credentials, connection mappings, and public website access, then rerun the in-depth audit.")
    update.plan_30.append("Resolve the reported access or provider issue and rerun the in-depth audit before treating missing data as a website or SEO gap.")
    update.sources.append("Fresh audit orchestration (partial; provider error recorded)")
    return update


def _safe_failure_detail(error: Exception) -> str:
    """Reduce provider failures to an actionable, non-sensitive client-safe code."""
    detail = " ".join(str(getattr(error, "detail", None) or error).split())
    if not detail or _SENSITIVE_FAILURE_TEXT.search(detail):
        return "a provider connection or execution error"
    return detail[:240]


def _safe_in_depth_client_update(database: Session, client: models.Client) -> ClientUpdate:
    """Keep one unavailable provider from suppressing the rest of a portfolio report."""
    try:
        return _in_depth_client_update(database, client)
    except (
        HTTPException,
        ValueError,
        URLError,
        TimeoutError,
        httpx.HTTPError,
        OSError,
        SearchConsoleIntegrationError,
        GoogleBusinessProfileIntegrationError,
    ) as error:
        return _blocked_client_update(client, error)


def generate_portfolio_update(
    database: Session,
    *,
    mode: str,
    client: models.Client | None = None,
) -> PortfolioUpdate:
    if mode not in {"simple", "in_depth"}:
        raise ValueError("client_update_mode_invalid")
    notes: list[str] = []
    total_active_clients = None
    if client is not None:
        clients = [client]
    else:
        total_active_clients = database.scalar(
            select(func.count()).select_from(models.Client).where(models.Client.archived_at.is_(None))
        ) or 0
        clients = list(
            database.scalars(
                select(models.Client)
                .where(models.Client.archived_at.is_(None))
                .order_by(models.Client.business_name.asc())
                .limit(MAX_PORTFOLIO_CLIENTS)
            )
        )
        if total_active_clients > MAX_PORTFOLIO_CLIENTS:
            notes.append(
                f"Portfolio scope is capped at {MAX_PORTFOLIO_CLIENTS} clients; "
                f"showing {len(clients)} of {total_active_clients}. Request a specific client or segment for the remainder."
            )
    if mode == "in_depth":
        from app.subscription_service import require_fulfillment_entitlement

        for item in clients:
            require_fulfillment_entitlement(database, item.id)
    if mode == "in_depth":
        from app.routes.website_metrics import sync_metrics

        try:
            result = sync_metrics(schemas.WebsiteMetricSyncRequest(window_days=30), database)
            notes.append(
                f"Portfolio analytics refresh completed: {len(result['snapshots'])} snapshots; "
                f"{len(result['unmatched_tracker_sites'])} unmatched tracker sites."
            )
        except (HTTPException, URLError, TimeoutError, ValueError, OSError) as error:
            detail = getattr(error, "detail", None) or str(error)
            notes.append(f"Portfolio analytics refresh failed: {detail}. Per-client reports explain the access needed.")
    reports = []
    for item in clients:
        update = _safe_in_depth_client_update(database, item) if mode == "in_depth" else _simple_client_update(database, item)
        if mode == "in_depth":
            _persist_audit_findings(database, update)
        reports.append(update)
    return PortfolioUpdate(mode=mode, clients=reports, portfolio_notes=notes)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def render_slack_update(report: PortfolioUpdate) -> str:
    depth = "In-depth fresh audit" if report.mode == "in_depth" else "Simple saved-data update"
    lines = [f"*{depth} · {len(report.clients)} client{'s' if len(report.clients) != 1 else ''}*"]
    lines.extend(f"_{note}_" for note in report.portfolio_notes)
    for client in report.clients:
        lines.append(f"\n*{client.business_name}* · `{client.status}` · `{client.client_id}`")
        for label, values in (
            ("Verified now", client.facts),
            ("Gaps", client.gaps),
            ("Could not verify", client.blockers),
            ("Needed to continue", client.needs),
            ("Next 0–30 days", client.plan_30),
            ("Days 31–60", client.plan_60),
            ("Days 61–90", client.plan_90),
            ("Sources", client.sources),
        ):
            values = _unique(values)
            if values:
                lines.append(f"*{label}:*")
                lines.extend(f"• {value}" for value in values)
    text = "\n".join(lines)
    if len(text) > MAX_SLACK_REPORT_CHARS:
        text = text[: MAX_SLACK_REPORT_CHARS - 180].rstrip() + "\n\n_Report truncated at Slack’s safe message limit. Run the in-depth report from an individual client channel for full detail._"
    return text
