"""Server-rendered dashboard pages for the agency owner.

Phase 4 starts with only the client-list screen. Keeping this route separate
from the JSON API routes makes the browser interface easy to find and change.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from html import escape
import json
import os
from pathlib import Path
from typing import Optional, Union
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.agency_access_service import require_capability
from app.daily_planning_service import DailyPlanTaskError, convert_plan_item_to_task, generate_daily_plans
from app.database import get_database
from app.routes.agency import create_member, update_member
from app.readiness_service import build_client_launch_readiness, build_readiness
from app.client_provider_verification import verify_client_providers

router = APIRouter(tags=["dashboard"])

TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "client_list.html"
CONNECTIONS_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "connections.html"
CLIENT_WORKSPACE_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "client_workspace.html"
ONBOARDING_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "onboarding_form.html"
INTAKE_FORM_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "intake_form.html"
MEMBERS_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "agency_members.html"


@dataclass
class ClientSummary:
    """The exact information needed for one row on the client-list screen."""

    id: str
    business_name: str
    onboarding_status: str
    profile_status: str
    service_start_date: date
    action_required: bool
    next_action: str
    website_url: Optional[str]
    website_project: Optional[str]


def build_client_summaries(database: Session, linked_only: bool = False) -> list[ClientSummary]:
    """Convert saved client and intake records into readable dashboard rows."""
    clients = list(database.scalars(select(models.Client)))
    clients_with_intakes = set(database.scalars(select(models.Intake.client_id).distinct()))
    official_profile_client_ids = set(
        database.scalars(select(models.OfficialProfile.client_id).distinct())
    )
    pending_profile_client_ids = set(
        database.scalars(
            select(models.ProfileVersion.client_id)
            .where(models.ProfileVersion.status == "pending")
            .distinct()
        )
    )
    rejected_profile_client_ids = set(
        database.scalars(
            select(models.ProfileVersion.client_id)
            .where(models.ProfileVersion.status == "rejected")
            .distinct()
        )
    )
    proposed_task_client_ids = set(
        database.scalars(
            select(models.Task.client_id).where(models.Task.status == "proposed").distinct()
        )
    )
    websites = {
        connection.client_id: connection
        for connection in database.scalars(select(models.WebsiteConnection))
    }
    if linked_only:
        clients = [
            client
            for client in clients
            if client.id in websites
            and websites[client.id].source == "confirmed_vercel_import"
        ]

    summaries = []
    for client in clients:
        has_intake = client.id in clients_with_intakes
        website = websites.get(client.id)
        if client.id in official_profile_client_ids:
            profile_status = "Official"
        elif client.id in pending_profile_client_ids:
            profile_status = "Review needed"
        elif client.id in rejected_profile_client_ids:
            profile_status = "Correction needed"
        else:
            profile_status = "Not started"

        if not has_intake:
            action_required, next_action = True, "Submit onboarding"
        elif client.id in pending_profile_client_ids:
            action_required, next_action = True, "Review profile"
        elif client.id in rejected_profile_client_ids:
            action_required, next_action = True, "Correct profile"
        elif client.id in proposed_task_client_ids:
            action_required, next_action = True, "Approve task"
        elif client.id not in official_profile_client_ids:
            action_required, next_action = False, "Waiting for proposal"
        else:
            action_required, next_action = False, "Monitoring"
        summaries.append(
            ClientSummary(
                id=client.id,
                business_name=client.business_name,
                onboarding_status="Submitted" if has_intake else "Not started",
                profile_status=profile_status,
                service_start_date=client.service_start_date,
                action_required=action_required,
                next_action=next_action,
                website_url=website.production_url if website else None,
                website_project=website.project_name if website else None,
            )
        )

    # Owner actions come first. Business name keeps the order predictable.
    return sorted(
        summaries,
        key=lambda summary: (not summary.action_required, summary.business_name.casefold()),
    )


def render_client_row(summary: ClientSummary) -> str:
    """Render one escaped client row so saved text cannot become browser code."""
    action_class = "action-required" if summary.action_required else "action-waiting"
    action_label = "Action required" if summary.action_required else "No owner action"
    website_link = (
        f'<a href="{escape(summary.website_url)}" target="_blank" rel="noopener" '
        f'aria-label="Open {escape(summary.business_name)} website">Website</a>'
        if summary.website_url
        else ""
    )
    return f"""
        <article class="client-row" data-client-id="{escape(summary.id)}">
          <div class="client-identity">
            <div>
              <a class="client-name" href="/dashboard/clients/{escape(summary.id)}">{escape(summary.business_name)}</a>
              <span class="client-meta">
                <code>{escape(summary.id)}</code>
                <span aria-hidden="true">·</span>
                starts <time datetime="{summary.service_start_date.isoformat()}">{summary.service_start_date.strftime('%b %d, %Y')}</time>
              </span>
            </div>
          </div>
          <div class="record-statuses">
            <span class="field-status"><small>Onboarding</small><span class="status status-neutral">{summary.onboarding_status}</span></span>
            <span class="field-status"><small>Profile</small><span class="status status-muted">{summary.profile_status}</span></span>
          </div>
          <div class="record-action">
            <span class="action {action_class}">{action_label}</span>
            <span class="next-action">{summary.next_action}</span>
          </div>
          <span class="record-links">
            {website_link}
            <a href="/dashboard/clients/{escape(summary.id)}" aria-label="Open {escape(summary.business_name)} workspace">Open</a>
            <a href="/dashboard/clients/{escape(summary.id)}/metrics" aria-label="Open {escape(summary.business_name)} metrics">Metrics</a>
            <a href="/dashboard/clients/{escape(summary.id)}/health" aria-label="Open {escape(summary.business_name)} health">Health</a>
            <a href="/dashboard/clients/{escape(summary.id)}/reports" aria-label="Open {escape(summary.business_name)} reports">Reports</a>
          </span>
        </article>
    """


@router.get("/", include_in_schema=False)
def dashboard_home() -> RedirectResponse:
    """Make the browser root a simple entrance to the owner dashboard."""
    return RedirectResponse(url="/dashboard")


@router.get("/dashboard", response_class=HTMLResponse)
def client_list_dashboard(
    linked_only: bool = False,
    database: Session = Depends(get_database),
) -> HTMLResponse:
    """Show all clients and make the next required owner action obvious."""
    summaries = build_client_summaries(database, linked_only=linked_only)
    action_count = sum(summary.action_required for summary in summaries)
    submitted_count = sum(summary.onboarding_status == "Submitted" for summary in summaries)
    rows = "".join(render_client_row(summary) for summary in summaries)

    if not rows:
        rows = """
          <div class="empty-state">
            No clients yet. Create a client through the API to begin onboarding.
          </div>
        """

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    page = (
        template.replace("{{CLIENT_COUNT}}", str(len(summaries)))
        .replace("{{ACTION_COUNT}}", str(action_count))
        .replace("{{SUBMITTED_COUNT}}", str(submitted_count))
        .replace("{{CLIENT_ROWS}}", rows)
    )
    return HTMLResponse(page)


@router.get("/dashboard/release-readiness", response_class=HTMLResponse)
def release_readiness_dashboard(database: Session = Depends(get_database)) -> HTMLResponse:
    """Give the agency owner a secret-free, actionable full-release gate."""
    result = build_readiness(database, "full")
    rows = "".join(
        f'''<article class="connection-client">
          <div><strong>{escape(str(check["key"]))}</strong><p>{escape(str(check["detail"]))}</p></div>
          <span class="connection-state {"ready" if check["status"] == "passed" else "missing"}">{escape(str(check["status"]))}</span>
          {f'<p>{escape(str(check["remediation"]))}</p>' if check.get("remediation") else ""}
        </article>'''
        for check in result["checks"]
    )
    status_label = "Ready for release" if result["status"] == "ready" else "Release blocked"
    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Release readiness · Max</title><link rel="stylesheet" href="/static/dashboard.css"></head>
<body><div class="app-shell"><aside class="sidebar"><a class="brand" href="/dashboard">Max</a>
<p class="product-context">Agency operations</p><nav class="sidebar-nav" aria-label="Workspace navigation">
<a class="nav-item" href="/dashboard">Clients</a><a class="nav-item" href="/dashboard/connections">Connections</a>
<a class="nav-item active" href="/dashboard/release-readiness" aria-current="page">Release readiness</a>
<a class="nav-item" href="/dashboard/notifications">Notifications</a></nav></aside>
<div class="workspace"><main id="main-content"><section class="page-heading"><div><h1>Release readiness</h1>
<p>{escape(status_label)} · {result["summary"]["passed"]} passed, {result["summary"]["blocked"]} blocked.</p></div></section>
<section class="client-directory" aria-label="Release checks">{rows}</section></main></div></div></body></html>'''
    return HTMLResponse(page)


def _member_rows(members: list[models.AgencyMember]) -> str:
    rows = []
    for member in members:
        status = "Active" if member.active else "Inactive"
        slack = member.slack_user_id or "Not mapped"
        action = "Deactivate" if member.active else "Reactivate"
        next_active = "false" if member.active else "true"
        rows.append(
            f'''<article class="member-row">
              <div><strong>{escape(member.display_name)}</strong><span>{escape(member.email)}</span></div>
              <div><span class="role-badge role-{escape(member.role)}">{escape(member.role)}</span><span class="member-status">{escape(status)}</span></div>
              <div><code>{escape(slack)}</code></div>
              <form method="post" action="/dashboard/agency/members/{escape(member.id)}" class="member-edit-form">
                <input type="hidden" name="display_name" value="{escape(member.display_name)}">
                <label>Role<select name="role"><option value="owner" {'selected' if member.role == 'owner' else ''}>Owner</option><option value="admin" {'selected' if member.role == 'admin' else ''}>Admin</option><option value="operator" {'selected' if member.role == 'operator' else ''}>Operator</option><option value="viewer" {'selected' if member.role == 'viewer' else ''}>Viewer</option></select></label>
                <label>Slack user ID<input name="slack_user_id" value="{escape(member.slack_user_id or '')}" placeholder="U123…"></label>
                <input type="hidden" name="active" value="{next_active}">
                <button type="submit" name="action" value="update">Save</button>
                <button type="submit" name="action" value="toggle" class="secondary">{action}</button>
              </form>
            </article>'''
        )
    return "".join(rows) or '<p class="empty-state">No agency members have been added yet.</p>'


@router.get("/dashboard/agency/members", response_class=HTMLResponse)
def agency_members_dashboard(
    request: Request,
    database: Session = Depends(get_database),
    message: str = "",
    error: str = "",
) -> HTMLResponse:
    """Owner-only member directory with role and Slack mapping controls."""
    require_capability(request, database, "manage_members")
    members = list(database.scalars(select(models.AgencyMember).order_by(models.AgencyMember.email)))
    template = MEMBERS_TEMPLATE_PATH.read_text(encoding="utf-8")
    notice = (
        f'<p class="workspace-message success">{escape(message)}</p>' if message else
        f'<p class="workspace-message error">{escape(error)}</p>' if error else ""
    )
    return HTMLResponse(
        template.replace("{{NOTICE}}", notice)
        .replace("{{MEMBER_COUNT}}", str(len(members)))
        .replace("{{ACTIVE_COUNT}}", str(sum(member.active for member in members)))
        .replace("{{MEMBER_ROWS}}", _member_rows(members))
    )


@router.post("/dashboard/agency/members", response_class=RedirectResponse)
def create_member_from_dashboard(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    role: str = Form("operator"),
    slack_user_id: str = Form(""),
    database: Session = Depends(get_database),
) -> RedirectResponse:
    from pydantic import ValidationError

    try:
        create_member(
            schemas.AgencyMemberCreate(
                email=email,
                display_name=display_name,
                role=role,
                slack_user_id=slack_user_id or None,
            ),
            request,
            database,
        )
        return RedirectResponse("/dashboard/agency/members?message=Member%20added", status_code=303)
    except (HTTPException, ValidationError, ValueError) as error:
        detail = getattr(error, "detail", None) or str(error)
        return RedirectResponse(f"/dashboard/agency/members?error={quote(str(detail)[:180])}", status_code=303)


@router.post("/dashboard/agency/members/{member_id}", response_class=RedirectResponse)
def update_member_from_dashboard(
    member_id: str,
    request: Request,
    display_name: str = Form(...),
    role: str = Form(...),
    slack_user_id: str = Form(""),
    active: str = Form("true"),
    action: str = Form("update"),
    database: Session = Depends(get_database),
) -> RedirectResponse:
    from pydantic import ValidationError

    try:
        current_member = database.get(models.AgencyMember, member_id)
        if current_member is None:
            raise HTTPException(status_code=404, detail="agency_member_not_found")
        target_active = (active.casefold() == "true") if action == "toggle" else current_member.active
        update_member(
            member_id,
            schemas.AgencyMemberUpdate(
                display_name=display_name,
                role=role,
                slack_user_id=slack_user_id or None,
                active=target_active,
            ),
            request,
            database,
        )
        return RedirectResponse("/dashboard/agency/members?message=Member%20updated", status_code=303)
    except (HTTPException, ValidationError, ValueError) as error:
        detail = getattr(error, "detail", None) or str(error)
        return RedirectResponse(f"/dashboard/agency/members?error={quote(str(detail)[:180])}", status_code=303)


def _onboarding_page(error: Optional[str] = None, values: Optional[dict[str, str]] = None) -> HTMLResponse:
    """Render the browser form without putting submitted data into a URL."""
    values = values or {}
    template = ONBOARDING_TEMPLATE_PATH.read_text(encoding="utf-8")
    fields = ("business_name", "service_start_date", "phone_number", "email", "domain", "google_business_profile", "brand_colors", "business_hours", "service_areas", "enabled_workflows", "asset_references")
    for field in fields:
        template = template.replace("{{" + field.upper() + "}}", escape(values.get(field, "")))
    message = f'<p class="workspace-message error">{escape(error)}</p>' if error else ""
    return HTMLResponse(template.replace("{{ERROR}}", message))


def _list_input(value: str) -> list[str]:
    """Turn a beginner-friendly comma-separated field into stored list data."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _asset_references(value: str) -> list[str]:
    """Use one line per external asset reference and ignore blank lines."""
    return [item.strip() for item in value.splitlines() if item.strip()]


def _save_asset_references(database: Session, client_id: str, references: list[str]) -> None:
    """Store only new asset references, always under their one client."""
    existing = set(database.scalars(select(models.ClientAsset.reference).where(models.ClientAsset.client_id == client_id)))
    for reference in references:
        if reference not in existing:
            database.add(models.ClientAsset(client_id=client_id, reference=reference[:2000], label=reference.rsplit("/", 1)[-1][:300] or "Client asset", source="onboarding_reference"))


def _intake_form_page(client: models.Client, error: Optional[str] = None, values: Optional[dict[str, str]] = None) -> HTMLResponse:
    """Render the form for a new intake version belonging to one known client."""
    values = values or {}
    template = INTAKE_FORM_TEMPLATE_PATH.read_text(encoding="utf-8")
    template = template.replace("{{CLIENT_ID}}", escape(client.id)).replace("{{CLIENT_NAME}}", escape(client.business_name))
    fields = ("phone_number", "email", "domain", "google_business_profile", "brand_colors", "business_hours", "service_areas", "enabled_workflows", "asset_references")
    for field in fields:
        template = template.replace("{{" + field.upper() + "}}", escape(values.get(field, "")))
    message = f'<p class="workspace-message error">{escape(error)}</p>' if error else ""
    return HTMLResponse(template.replace("{{ERROR}}", message))


@router.get("/dashboard/onboarding", response_class=HTMLResponse)
def new_client_onboarding_form() -> HTMLResponse:
    """Show the smallest complete browser flow for a new client intake."""
    return _onboarding_page()


@router.post("/dashboard/onboarding", response_class=HTMLResponse, response_model=None)
def create_client_from_onboarding_form(
    business_name: str = Form(...),
    service_start_date: str = Form(...),
    phone_number: str = Form(...),
    email: str = Form(...),
    domain: str = Form(...),
    google_business_profile: str = Form(...),
    brand_colors: str = Form(...),
    business_hours: str = Form(...),
    service_areas: str = Form(...),
    enabled_workflows: str = Form(...),
    asset_references: str = Form(""),
    database: Session = Depends(get_database),
) -> Union[HTMLResponse, RedirectResponse]:
    """Create a client and first intake in one transaction-like browser action."""
    values = {
        "business_name": business_name, "service_start_date": service_start_date,
        "phone_number": phone_number, "email": email, "domain": domain,
        "google_business_profile": google_business_profile, "brand_colors": brand_colors,
        "business_hours": business_hours, "service_areas": service_areas, "enabled_workflows": enabled_workflows, "asset_references": asset_references,
    }
    required_lists = {"brand_colors": _list_input(brand_colors), "service_areas": _list_input(service_areas), "enabled_workflows": _list_input(enabled_workflows)}
    try:
        parsed_date = date.fromisoformat(service_start_date)
    except ValueError:
        return _onboarding_page("Service start date must use a valid date.", values)
    if not all(item.strip() for item in (business_name, phone_number, email, domain, google_business_profile, business_hours)) or not all(required_lists.values()):
        return _onboarding_page("Complete every field before saving the intake.", values)
    if database.scalar(select(models.Client).where(func.lower(models.Client.business_name) == business_name.strip().lower())):
        return _onboarding_page("A client with that business name already exists. Open that client to add a new intake.", values)
    # Keep the validation rules equivalent to the API, including a real email check.
    try:
        intake_data = {
            "phone_number": phone_number.strip(), "email": email.strip(), "domain": domain.strip(),
            "google_business_profile": google_business_profile.strip(), "brand_colors": required_lists["brand_colors"],
            "business_hours": business_hours.strip(), "service_areas": required_lists["service_areas"],
            "enabled_workflows": required_lists["enabled_workflows"],
        }
        # Pydantic is the shared source of truth for the intake field validation.
        from app.schemas import IntakeCreate
        validated = IntakeCreate(**intake_data)
    except Exception as error:
        return _onboarding_page(f"Check the form: {error}", values)
    client = models.Client(business_name=business_name.strip(), service_start_date=parsed_date)
    database.add(client)
    database.flush()
    intake = models.Intake(client_id=client.id, submitted_at=datetime.utcnow(), **validated.model_dump())
    database.add(intake)
    database.flush()
    _save_asset_references(database, client.id, _asset_references(asset_references))
    from app.onboarding_automation import queue_onboarding_run

    queue_onboarding_run(database, client.id, intake.id)
    database.commit()
    return RedirectResponse(url=f"/dashboard/clients/{client.id}?section=intake&notice=Client+and+original+intake+saved", status_code=303)


@router.get("/dashboard/clients/{client_id}/intakes/new", response_class=HTMLResponse)
def new_intake_form(client_id: str, database: Session = Depends(get_database)) -> HTMLResponse:
    """Show a form that creates a new immutable intake for an existing client."""
    return _intake_form_page(_client_or_404(database, client_id))


@router.post("/dashboard/clients/{client_id}/intakes/new", response_class=HTMLResponse, response_model=None)
def submit_new_intake_from_form(
    client_id: str,
    phone_number: str = Form(...),
    email: str = Form(...),
    domain: str = Form(...),
    google_business_profile: str = Form(...),
    brand_colors: str = Form(...),
    business_hours: str = Form(...),
    service_areas: str = Form(...),
    enabled_workflows: str = Form(...),
    asset_references: str = Form(""),
    database: Session = Depends(get_database),
) -> Union[HTMLResponse, RedirectResponse]:
    """Save a second intake without mutating the original one."""
    client = _client_or_404(database, client_id)
    values = {"phone_number": phone_number, "email": email, "domain": domain, "google_business_profile": google_business_profile, "brand_colors": brand_colors, "business_hours": business_hours, "service_areas": service_areas, "enabled_workflows": enabled_workflows, "asset_references": asset_references}
    payload = {
        "phone_number": phone_number.strip(), "email": email.strip(), "domain": domain.strip(),
        "google_business_profile": google_business_profile.strip(), "brand_colors": _list_input(brand_colors),
        "business_hours": business_hours.strip(), "service_areas": _list_input(service_areas),
        "enabled_workflows": _list_input(enabled_workflows),
    }
    try:
        from app.schemas import IntakeCreate
        validated = IntakeCreate(**payload)
    except Exception as error:
        return _intake_form_page(client, f"Check the form: {error}", values)
    intake = models.Intake(client_id=client.id, submitted_at=datetime.utcnow(), **validated.model_dump())
    database.add(intake)
    database.flush()
    _save_asset_references(database, client.id, _asset_references(asset_references))
    from app.onboarding_automation import queue_onboarding_run

    queue_onboarding_run(database, client.id, intake.id)
    database.commit()
    return RedirectResponse(url=f"/dashboard/clients/{client.id}?section=intake&notice=New+intake+version+saved", status_code=303)


def _client_or_404(database: Session, client_id: str) -> models.Client:
    client = database.get(models.Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _pretty_json(value: object) -> str:
    """Format saved JSON for review while escaping it before browser output."""
    return escape(json.dumps(value, indent=2, sort_keys=True, default=str))


def _format_time(value: Optional[datetime]) -> str:
    if value is None:
        return "Not decided"
    return value.strftime("%b %d, %Y at %-I:%M %p")


def _workspace_tabs(client_id: str, section: str) -> str:
    tabs = (("overview", "Overview"), ("plan", "Daily plan"), ("intake", "Original intake"), ("review", "Profile review"), ("official", "Official profile"))
    return "".join(
        f'<a class="workspace-tab {"active" if name == section else ""}" href="/dashboard/clients/{escape(client_id)}?section={name}">{label}</a>'
        for name, label in tabs
    )


def _latest_intake(database: Session, client_id: str) -> Optional[models.Intake]:
    return database.scalar(
        select(models.Intake)
        .where(models.Intake.client_id == client_id)
        .order_by(models.Intake.submitted_at.desc(), models.Intake.id.desc())
    )


def _automation_panel(database: Session, client: models.Client) -> str:
    intake = _latest_intake(database, client.id)
    run = database.scalar(
        select(models.OnboardingAutomationRun).where(
            models.OnboardingAutomationRun.client_id == client.id,
            models.OnboardingAutomationRun.intake_id == intake.id,
        )
    ) if intake else None
    if run is None:
        if _latest_intake(database, client.id) is None:
            return ""
        return f'''<section class="automation-panel"><header><div><p class="eyebrow">Automatic onboarding</p><h2>Not started</h2></div></header><p>Start service discovery and profile preparation for this client's latest intake.</p><form method="post" action="/dashboard/clients/{escape(client.id)}/onboarding-automation"><button type="submit">Start automation</button></form></section>'''
    labels = {
        "interpretation": "OpenAI profile",
        "slack": "Slack channel",
        "vercel": "Vercel project",
        "github": "GitHub repository",
        "website_analytics": "Website analytics",
        "profile": "Profile approval",
        "tasks": "Task proposals",
    }
    step_rows = "".join(
        f'<li><span>{escape(labels.get(name, name.replace("_", " ").title()))}</span><strong class="automation-state status-{escape(str((run.steps.get(name) or {}).get("status", "pending")))}">{escape(str((run.steps.get(name) or {}).get("status", "pending")).replace("_", " ").title())}</strong></li>'
        for name in labels
    )
    candidates = list(
        database.scalars(
            select(models.ConnectionCandidate).where(
                models.ConnectionCandidate.run_id == run.id,
                models.ConnectionCandidate.status == "pending",
            ).order_by(models.ConnectionCandidate.provider, models.ConnectionCandidate.display_name)
        )
    )
    candidate_rows = "".join(
        f'''<article class="candidate-row"><div><small>{escape(item.provider.replace("_", " ").title())}</small><strong>{escape(item.display_name)}</strong><span>{escape(str(item.match_evidence.get("reason", "Needs confirmation")).replace("_", " "))}</span></div><div class="candidate-actions"><form method="post" action="/dashboard/connection-candidates/{escape(item.id)}/decision"><input type="hidden" name="decision" value="approve"><input type="hidden" name="decided_by" value="Agency Owner"><button type="submit">Approve match</button></form><form method="post" action="/dashboard/connection-candidates/{escape(item.id)}/decision"><input type="hidden" name="decision" value="reject"><input type="hidden" name="decided_by" value="Agency Owner"><input type="hidden" name="reason" value="Not the correct client resource"><button type="submit">Reject</button></form></div></article>'''
        for item in candidates
    )
    error = f'<p class="automation-error">Blocked: {escape(run.last_error)}</p>' if run.last_error else ""
    resume = ""
    if run.status == "blocked":
        resume = f'<form method="post" action="/dashboard/clients/{escape(client.id)}/onboarding-automation"><button type="submit">Retry automation</button></form>'
    return f'''<section class="automation-panel"><header><div><p class="eyebrow">Automatic onboarding</p><h2>{escape(run.status.replace("_", " ").title())}</h2></div><code>{escape(run.id)}</code></header>{error}<ol class="automation-steps">{step_rows}</ol>{candidate_rows}{resume}</section>'''


def _launch_check_rows(checks: list[dict]) -> str:
    rows = []
    for check in checks:
        remediation = (
            f'<small>{escape(str(check["remediation"]))}</small>'
            if check.get("remediation")
            else ""
        )
        rows.append(
            f'<li><strong>{escape(str(check["key"]).replace("_", " ").title())}</strong>'
            f'<span>{escape(str(check["detail"]))}</span>{remediation}</li>'
        )
    return "".join(rows)


def _workspace_overview(database: Session, client: models.Client) -> str:
    intake = _latest_intake(database, client.id)
    pending = database.scalar(
        select(models.ProfileVersion)
        .where(models.ProfileVersion.client_id == client.id, models.ProfileVersion.status == "pending")
        .order_by(models.ProfileVersion.version_number.desc())
    )
    official = database.scalar(select(models.OfficialProfile).where(models.OfficialProfile.client_id == client.id))
    next_action = (
        ("Submit onboarding", "No intake has been received yet.", "intake") if intake is None
        else ("Review proposed profile", "A proposed profile is waiting for your decision.", "review") if pending
        else ("Profile is official", "This client has an approved profile.", "official") if official
        else ("Interpret intake", "The intake has not been turned into a proposal yet.", "intake")
    )
    intake_count = len(list(database.scalars(select(models.Intake.id).where(models.Intake.client_id == client.id))))
    version_count = len(list(database.scalars(select(models.ProfileVersion.id).where(models.ProfileVersion.client_id == client.id))))
    assets = list(
        database.scalars(
            select(models.ClientAsset).where(models.ClientAsset.client_id == client.id).order_by(models.ClientAsset.added_at)
        )
    )
    asset_items = "".join(f"<li>{escape(asset.label)}</li>" for asset in assets) or "<li>No asset links saved yet.</li>"
    automation_panel = _automation_panel(database, client)
    launch = build_client_launch_readiness(database, client.id)
    launch_status = "Ready for recurring fulfillment" if launch["status"] == "ready" else "Launch blocked"
    launch_rows = _launch_check_rows(launch["required_checks"] + launch["recommended_checks"])
    launch_panel = f'''<section class="automation-panel"><header><div><p class="eyebrow">Client launch gate</p><h2>{escape(launch_status)}</h2></div><a class="secondary-action" href="/clients/{escape(client.id)}/launch-readiness">JSON diagnostics</a></header><p>{launch["summary"]["required_passed"]}/{launch["summary"]["required_passed"] + launch["summary"]["required_blocked"]} required checks passed; {launch["summary"]["recommended_blocked"]} recommended evidence source(s) still missing.</p><form method="post" action="/dashboard/clients/{escape(client.id)}/provider-verification"><button type="submit">Run live provider checks</button></form><ul class="report-list">{launch_rows}</ul></section>'''
    return f"""
      <section class="next-step-panel">
        <p class="eyebrow">Next required action</p><h2>{next_action[0]}</h2><p>{next_action[1]}</p>
        <a class="primary-action" href="/dashboard/clients/{escape(client.id)}?section={next_action[2]}">Open section</a>
      </section>
      {automation_panel}
      {launch_panel}
      <section class="workspace-summary" aria-label="Client record summary">
        <article><small>Original intakes</small><strong>{intake_count}</strong><a href="/dashboard/clients/{escape(client.id)}?section=intake">View history</a></article>
        <article><small>Profile versions</small><strong>{version_count}</strong><a href="/dashboard/clients/{escape(client.id)}?section=review">Review versions</a></article>
        <article><small>Official profile</small><strong>{"Ready" if official else "None"}</strong><a href="/dashboard/clients/{escape(client.id)}?section=official">Open record</a></article>
      </section>
      <section class="workspace-note"><h2>Approved assets</h2><p>These {len(assets)} reference(s) belong only to this client. Max stores file links now; direct file uploads can be added when storage is connected.</p><ul class="asset-list">{asset_items}</ul></section>
      <section class="workspace-note"><h2>How this works</h2><p>Max keeps the original intake unchanged. A proposal can be reviewed in versions. Only an approved version becomes the official client profile.</p></section>
    """


def _workspace_intake(database: Session, client: models.Client) -> str:
    intakes = list(database.scalars(select(models.Intake).where(models.Intake.client_id == client.id).order_by(models.Intake.submitted_at.desc(), models.Intake.id.desc())))
    new_intake_link = f'<a class="primary-action" href="/dashboard/clients/{escape(client.id)}/intakes/new">Submit new intake</a>'
    if not intakes:
        return f'<section class="empty-workspace"><h2>No onboarding intake yet</h2><p>Submit the first intake for this existing client. The saved intake will appear here unchanged.</p>{new_intake_link}</section>'
    cards = []
    for intake in intakes:
        proposal = database.scalar(select(models.InterpretationProposal).where(models.InterpretationProposal.intake_id == intake.id))
        interpretation_action = (
            '<span class="muted-copy">Already interpreted</span>' if proposal else
            f'<form method="post" action="/dashboard/clients/{escape(client.id)}/intakes/{escape(intake.id)}/interpret"><button type="submit">Create proposal</button></form>'
        )
        payload = {
            "phone_number": intake.phone_number, "email": intake.email, "brand_colors": intake.brand_colors,
            "domain": intake.domain, "business_hours": intake.business_hours, "service_areas": intake.service_areas,
            "google_business_profile": intake.google_business_profile, "enabled_workflows": intake.enabled_workflows,
        }
        cards.append(f'''<article class="record-card"><header><div><p class="eyebrow">Original intake</p><h2>{escape(intake.id)}</h2><p>Submitted {_format_time(intake.submitted_at)}</p></div>{interpretation_action}</header><pre>{_pretty_json(payload)}</pre></article>''')
    return f'<section class="section-intro intake-section-heading"><div><h2>Original onboarding intake</h2><p>This is source information. It is never changed by interpretation, review, or approval.</p></div>{new_intake_link}</section>' + ''.join(cards)


def _workspace_review(database: Session, client: models.Client) -> str:
    versions = list(database.scalars(select(models.ProfileVersion).where(models.ProfileVersion.client_id == client.id).order_by(models.ProfileVersion.version_number.desc(), models.ProfileVersion.id.desc())))
    if not versions:
        return '<section class="empty-workspace"><h2>No proposed profile yet</h2><p>Open the original intake and create a proposal first.</p><a href="?section=intake">Open original intake</a></section>'
    cards = []
    for version in versions:
        intake = database.get(models.Intake, version.intake_id)
        source = {"phone_number": intake.phone_number, "email": intake.email, "domain": intake.domain, "brand_colors": intake.brand_colors, "business_hours": intake.business_hours, "service_areas": intake.service_areas, "google_business_profile": intake.google_business_profile, "enabled_workflows": intake.enabled_workflows} if intake else {"error": "Source intake unavailable"}
        actions = '<p class="decision-detail">No further action. This version is immutable.</p>'
        if version.status == "pending":
            actions = f'''<div class="review-actions"><form method="post" action="/dashboard/clients/{escape(client.id)}/profile-versions/{escape(version.id)}/decision"><input type="hidden" name="decision" value="approve"><input type="hidden" name="decision_maker" value="Agency Owner"><button class="primary-button" type="submit">Approve profile</button></form><form method="post" action="/dashboard/clients/{escape(client.id)}/profile-versions/{escape(version.id)}/decision" class="reject-decision"><input type="hidden" name="decision" value="reject"><label>Reason for rejection <input required name="reason" maxlength="1200" placeholder="What needs to change?"></label><input type="hidden" name="decision_maker" value="Agency Owner"><button type="submit">Reject with reason</button></form></div>'''
        elif version.status == "rejected":
            raw = escape(json.dumps(version.profile_data, indent=2, sort_keys=True))
            actions = f'''<details class="correction"><summary>Make a corrected version</summary><p>Change only what is needed. The rejected version remains in history.</p><form method="post" action="/dashboard/clients/{escape(client.id)}/profile-versions/{escape(version.id)}/correct"><label>Corrected profile data <textarea name="profile_data" rows="14" required>{raw}</textarea></label><input type="hidden" name="decision_maker" value="Agency Owner"><button type="submit">Create corrected version</button></form></details>'''
        reason = f'<p class="decision-detail">{escape(version.decision_reason or "No decision reason recorded")} · {_format_time(version.decided_at)}</p>' if version.status != "pending" else ''
        cards.append(f'''<article class="review-card"><header><div><p class="eyebrow">Profile version {version.version_number}</p><h2>{escape(version.status.title())}</h2>{reason}</div></header><div class="comparison-grid"><section><h3>Original intake</h3><pre>{_pretty_json(source)}</pre></section><section><h3>Proposed profile</h3><pre>{_pretty_json(version.profile_data)}</pre></section></div>{actions}</article>''')
    return '<section class="section-intro"><h2>Profile review</h2><p>Approve a pending proposal only when it is correct. Rejecting it keeps history and allows a new version.</p></section>' + ''.join(cards)


def _workspace_official(database: Session, client: models.Client) -> str:
    profile = database.scalar(select(models.OfficialProfile).where(models.OfficialProfile.client_id == client.id))
    if profile is None:
        return '<section class="empty-workspace"><h2>No official profile yet</h2><p>Only an approved profile version becomes official. Review the proposed profile first.</p><a href="?section=review">Open profile review</a></section>'
    return f'''<section class="section-intro"><h2>Official client profile</h2><p>This is the version Max may use for future work. It does not replace the original intake or earlier review history.</p></section><article class="record-card official-card"><header><div><p class="eyebrow">Approved version</p><h2>{escape(profile.approved_version_id)}</h2><p>Approved by {escape(profile.approved_by)} · {_format_time(profile.approved_at)}</p></div><span class="official-badge">Official</span></header><pre>{_pretty_json(profile.profile_data)}</pre></article>'''


def _workspace_plan(database: Session, client: models.Client) -> str:
    plan = database.scalar(
        select(models.DailyClientPlan).where(
            models.DailyClientPlan.client_id == client.id,
            models.DailyClientPlan.plan_date == date.today(),
        )
    )
    controls = f'''
      <section class="section-intro"><div><h2>Today's client plan</h2><p>Simple uses saved tasks and evidence. In-depth also refreshes available website, Search Console, analytics, and access signals.</p></div></section>
      <section class="workspace-note"><h2>Generate or refresh</h2>
        <form method="post" action="/dashboard/clients/{escape(client.id)}/daily-plan">
          <label>Depth <select name="depth"><option value="simple">Simple</option><option value="in_depth">In-depth live audit</option></select></label>
          <label>Focus <select name="focus"><option value="all">All work</option><option value="seo">SEO</option><option value="fulfillment">Fulfillment</option><option value="reporting">Reporting</option></select></label>
          <button class="primary-button" type="submit">Generate today's plan</button>
        </form>
      </section>'''
    if plan is None:
        return controls + '<section class="empty-workspace"><h2>No plan generated today</h2><p>Generate a simple plan now, or choose an in-depth audit when you want fresh external evidence and a 30–90 day roadmap.</p></section>'
    labels = {
        "ready_now": "Can do now",
        "needs_verification": "Verify today",
        "needs_approval": "Needs approval",
        "blocked": "Blocked or access needed",
        "recommended": "Recommended next",
    }
    groups = []
    for bucket in ("ready_now", "needs_verification", "needs_approval", "blocked", "recommended"):
        items = [(index, item) for index, item in enumerate(plan.items) if item.get("bucket") == bucket]
        if not items:
            continue
        cards = "".join(
            f'''<article class="record-card"><header><div><p class="eyebrow">Item {index + 1} · {escape(str(item.get("horizon", "today")).replace("_", " "))}</p><h3>{escape(str(item.get("title", "Untitled task")))}</h3></div></header><p>{escape(str(item.get("action", "")))}</p><p><strong>Next:</strong> {escape(str(item.get("next_step", "")))}</p><p class="muted-copy">Source: {escape(str(item.get("source", "unknown")))}</p>{(f'<p class="muted-copy">Linked task: <code>{escape(str(item.get("task_id")))}</code></p>' if item.get("task_id") else f'<form method="post" action="/dashboard/clients/{escape(client.id)}/daily-plan/items/{index}/task"><button type="submit">Create approval task</button></form>' if bucket in {"recommended", "blocked"} else "")}</article>'''
            for index, item in items
        )
        groups.append(f'<section class="workspace-note"><h2>{labels[bucket]}</h2>{cards}</section>')
    summary = plan.source_summary or {}
    evidence = f'''<section class="workspace-note"><h2>Evidence used</h2><p>{int(summary.get("verified_fact_count", 0))} verified facts · {int(summary.get("gap_count", 0))} gaps · {int(summary.get("blocker_count", 0))} blockers</p><p class="muted-copy">{escape(plan.depth.replace("_", " ").title())} · {escape(plan.focus.title())} · refreshed {escape(str(summary.get("refreshed_at", "unknown")))}</p></section>'''
    return controls + evidence + "".join(groups)


@router.get("/dashboard/clients/{client_id}", response_class=HTMLResponse)
def client_workspace_dashboard(client_id: str, section: str = "overview", notice: Optional[str] = None, error: Optional[str] = None, database: Session = Depends(get_database)) -> HTMLResponse:
    """Show one client's preserved intake, review history, and official profile."""
    client = _client_or_404(database, client_id)
    section = section if section in {"overview", "plan", "intake", "review", "official"} else "overview"
    official = database.scalar(select(models.OfficialProfile).where(models.OfficialProfile.client_id == client.id))
    content = {"overview": _workspace_overview, "plan": _workspace_plan, "intake": _workspace_intake, "review": _workspace_review, "official": _workspace_official}[section](database, client)
    banner = f'<p class="workspace-message success">{escape(notice)}</p>' if notice else (f'<p class="workspace-message error">{escape(error)}</p>' if error else "")
    page = CLIENT_WORKSPACE_TEMPLATE_PATH.read_text(encoding="utf-8")
    page = (page.replace("{{CLIENT_NAME}}", escape(client.business_name)).replace("{{CLIENT_ID}}", escape(client.id)).replace("{{SERVICE_START_DATE}}", client.service_start_date.strftime("%b %d, %Y")).replace("{{PROFILE_STATUS}}", "Official profile" if official else "Profile not approved").replace("{{WORKSPACE_TABS}}", _workspace_tabs(client.id, section)).replace("{{NOTICE}}", banner).replace("{{WORKSPACE_CONTENT}}", content))
    return HTMLResponse(page)


@router.post("/dashboard/clients/{client_id}/provider-verification", response_class=RedirectResponse)
def verify_client_providers_from_workspace(
    client_id: str,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    client = _client_or_404(database, client_id)
    try:
        result = verify_client_providers(database, client.id)
        database.commit()
        if result["status"] == "verified":
            message = "Live provider checks passed"
        else:
            message = f"Live provider checks found {result['summary']['failed']} issue(s)"
        return RedirectResponse(url=f"/dashboard/clients/{client.id}?notice={quote(message)}", status_code=303)
    except Exception:
        database.rollback()
        return RedirectResponse(url=f"/dashboard/clients/{client.id}?error=Provider+checks+could+not+complete", status_code=303)


@router.post("/dashboard/clients/{client_id}/daily-plan", response_class=RedirectResponse)
def generate_daily_plan_from_workspace(
    client_id: str,
    depth: str = Form("simple"),
    focus: str = Form("all"),
    database: Session = Depends(get_database),
) -> RedirectResponse:
    client = _client_or_404(database, client_id)
    if client.status == "archived":
        return RedirectResponse(url=f"/dashboard/clients/{client.id}?section=plan&error=Archived+clients+cannot+receive+new+plans", status_code=303)
    try:
        generate_daily_plans(database, client=client, depth=depth, focus=focus, created_by="Agency Owner")
        database.commit()
    except ValueError:
        database.rollback()
        return RedirectResponse(url=f"/dashboard/clients/{client.id}?section=plan&error=Unsupported+plan+settings", status_code=303)
    return RedirectResponse(url=f"/dashboard/clients/{client.id}?section=plan&notice=Today%27s+plan+is+ready", status_code=303)


@router.post("/dashboard/clients/{client_id}/daily-plan/items/{item_index}/task", response_class=RedirectResponse)
def convert_daily_plan_item_from_workspace(
    client_id: str,
    item_index: int,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    client = _client_or_404(database, client_id)
    plan = database.scalar(
        select(models.DailyClientPlan).where(
            models.DailyClientPlan.client_id == client.id,
            models.DailyClientPlan.plan_date == date.today(),
        )
    )
    if plan is None:
        return RedirectResponse(url=f"/dashboard/clients/{client.id}?section=plan&error=No+plan+exists+today", status_code=303)
    try:
        task, reused = convert_plan_item_to_task(database, plan, item_index, created_by="Agency Owner")
        database.commit()
    except DailyPlanTaskError as error:
        database.rollback()
        return RedirectResponse(url=f"/dashboard/clients/{client.id}?section=plan&error={quote(str(error))}", status_code=303)
    state = "already linked" if reused else "created for approval"
    return RedirectResponse(url=f"/dashboard/clients/{client.id}?section=plan&notice=Task+{quote(task.id)}+{quote(state)}", status_code=303)


@router.post("/dashboard/clients/{client_id}/intakes/{intake_id}/interpret", response_class=RedirectResponse)
def interpret_intake_from_workspace(client_id: str, intake_id: str, database: Session = Depends(get_database)) -> RedirectResponse:
    """Use the fake interpreter from the dashboard and preserve the source intake."""
    _client_or_404(database, client_id)
    intake = database.get(models.Intake, intake_id)
    if intake is None or intake.client_id != client_id:
        raise HTTPException(status_code=404, detail="Intake not found for this client")
    proposal = database.scalar(select(models.InterpretationProposal).where(models.InterpretationProposal.intake_id == intake.id))
    if proposal is None:
        from app import interpretation_service
        client = database.get(models.Client, client_id)
        assets = list(
            database.scalars(
                select(models.ClientAsset.reference)
                .where(models.ClientAsset.client_id == client_id)
                .order_by(models.ClientAsset.added_at, models.ClientAsset.id)
            )
        )
        profile, missing, conflicts, processing_status = interpretation_service.interpret(
            intake, client.business_name, assets
        )
        proposal = models.InterpretationProposal(intake_id=intake.id, client_id=client_id, profile_data=profile, missing_information=missing, conflicting_information=conflicts, processing_status=processing_status, processed_at=datetime.now(timezone.utc).replace(tzinfo=None))
        database.add(proposal)
        database.flush()
        database.add(models.ProfileVersion(source_proposal_id=proposal.id, intake_id=intake.id, client_id=client_id, version_number=1, profile_data=profile))
        database.commit()
    return RedirectResponse(url=f"/dashboard/clients/{client_id}?section=review&notice=Proposal+ready+for+review", status_code=303)


@router.post("/dashboard/clients/{client_id}/profile-versions/{version_id}/decision", response_class=RedirectResponse)
def decide_profile_from_workspace(client_id: str, version_id: str, decision: str = Form(...), decision_maker: str = Form(...), reason: Optional[str] = Form(None), database: Session = Depends(get_database)) -> RedirectResponse:
    """Approve or reject only this client's pending profile version."""
    _client_or_404(database, client_id)
    version = database.get(models.ProfileVersion, version_id)
    error = None
    if version is None or version.client_id != client_id:
        error = "Profile version not found for this client"
    elif version.status != "pending":
        error = "This profile version has already been decided"
    elif decision not in {"approve", "reject"}:
        error = "Choose approve or reject"
    elif decision == "reject" and not (reason or "").strip():
        error = "A rejection reason is required"
    elif decision == "approve" and database.scalar(select(models.OfficialProfile).where(models.OfficialProfile.client_id == client_id)):
        error = "This client already has an official profile"
    if error:
        return RedirectResponse(url=f"/dashboard/clients/{client_id}?section=review&error={escape(error)}", status_code=303)
    version.status = "approved" if decision == "approve" else "rejected"
    version.decision_maker = decision_maker.strip()
    version.decision_reason = (reason or "").strip() or None
    version.decided_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if version.status == "approved":
        database.add(models.OfficialProfile(client_id=client_id, approved_version_id=version.id, profile_data=version.profile_data, approved_by=version.decision_maker))
    database.commit()
    message = "Profile approved and made official" if decision == "approve" else "Profile rejected; you can now create a corrected version"
    return RedirectResponse(url=f"/dashboard/clients/{client_id}?section=review&notice={message.replace(' ', '+')}", status_code=303)


@router.post("/dashboard/clients/{client_id}/profile-versions/{version_id}/correct", response_class=RedirectResponse)
def correct_profile_from_workspace(client_id: str, version_id: str, profile_data: str = Form(...), decision_maker: str = Form(...), database: Session = Depends(get_database)) -> RedirectResponse:
    """Create a new pending version while retaining the rejected one."""
    _client_or_404(database, client_id)
    version = database.get(models.ProfileVersion, version_id)
    error = None
    try:
        corrected_data = json.loads(profile_data)
        if not isinstance(corrected_data, dict):
            error = "Corrected profile data must be a JSON object"
    except json.JSONDecodeError:
        error = "Corrected profile data must be valid JSON"
        corrected_data = {}
    if version is None or version.client_id != client_id:
        error = "Profile version not found for this client"
    elif version.status != "rejected":
        error = "Only a rejected profile version can be corrected"
    if error:
        return RedirectResponse(url=f"/dashboard/clients/{client_id}?section=review&error={error.replace(' ', '+')}", status_code=303)
    highest = database.scalar(select(models.ProfileVersion.version_number).where(models.ProfileVersion.source_proposal_id == version.source_proposal_id).order_by(models.ProfileVersion.version_number.desc())) or version.version_number
    database.add(models.ProfileVersion(source_proposal_id=version.source_proposal_id, intake_id=version.intake_id, client_id=client_id, version_number=highest + 1, profile_data=corrected_data))
    database.commit()
    return RedirectResponse(url=f"/dashboard/clients/{client_id}?section=review&notice=Corrected+profile+version+created", status_code=303)


def _configured(*names: str) -> bool:
    """Return setup state without reading a secret into page content."""
    return all(bool(os.getenv(name, "").strip()) for name in names)


@router.get("/dashboard/connections", response_class=HTMLResponse)
def connections_dashboard(database: Session = Depends(get_database)) -> HTMLResponse:
    """Show safe configuration and per-client connection readiness."""
    clients = list(database.scalars(select(models.Client).order_by(models.Client.business_name)))
    websites = {item.client_id: item for item in database.scalars(select(models.WebsiteConnection))}
    repositories = {
        item.client_id: item for item in database.scalars(select(models.GitHubRepositoryConnection))
    }
    search_console = {
        item.client_id: item for item in database.scalars(select(models.SearchConsoleConnection))
    }
    slack_channels = {
        item.client_id: item for item in database.scalars(select(models.SlackChannelConnection))
    }
    provider_rows = [
        ("GitHub App", _configured("GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_APP_INSTALLATION_ID"), "Read-only repository verification"),
        ("Vercel", _configured("VERCEL_API_TOKEN"), "Read-only project verification"),
        ("Google", _configured("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"), "Search Console read-only import"),
        ("Slack", _configured("SLACK_BOT_TOKEN", "SLACK_WORKSPACE_ID"), "Public client channels and meaningful notifications"),
    ]
    provider_html = "".join(
        f'<article class="connection-provider"><strong>{escape(name)}</strong><span class="connection-state {"ready" if configured else "missing"}">{"Configured" if configured else "Needs setup"}</span><p>{escape(description)}</p></article>'
        for name, configured, description in provider_rows
    )
    client_html = "".join(
        f"""<article class="connection-client">
          <div><a href="/clients/{escape(client.id)}">{escape(client.business_name)}</a><small>{escape(client.id)}</small></div>
          <span class="connection-state {'ready' if client.id in repositories and repositories[client.id].connection_status == 'connected' else 'missing'}">{'Verified' if client.id in repositories and repositories[client.id].connection_status == 'connected' else 'Not verified'}</span>
          <span class="connection-state {'ready' if client.id in websites else 'missing'}">{'Linked' if client.id in websites else 'Not linked'}</span>
          <span class="connection-state {'ready' if client.id in search_console else 'missing'}">{'Linked' if client.id in search_console else 'Not linked'}</span>
          <span class="connection-state {'ready' if client.id in slack_channels else 'missing'}">{'Linked' if client.id in slack_channels else 'Not linked'}</span>
        </article>"""
        for client in clients
    ) or '<p class="empty-state">No clients exist yet.</p>'
    page = CONNECTIONS_TEMPLATE_PATH.read_text(encoding="utf-8")
    page = page.replace("{{PROVIDER_ROWS}}", provider_html).replace("{{CLIENT_ROWS}}", client_html)
    return HTMLResponse(page)
