"""Durable automatic onboarding orchestration and provider matching."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import os
import re
import inspect
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import models, openai_service
from app.ai_cost_service import AIBudgetExceeded, ensure_budget, record_usage
from app.audit import record_event
from app.github_service import GitHubAppAdapter, GitHubIntegrationError, GitHubRepository
from app.notification_service import NotificationEvent, deliver_notification, notify_task_approval
from app.prompt_service import compile_prompt
from app.slack_service import SlackIntegrationError, connect_client_channel
from app.vercel_service import VercelAdapter, VercelIntegrationError, VercelProject
from app.website_analytics import fetch_summary


STEPS = ("interpretation", "slack", "vercel", "github", "website_analytics", "profile", "tasks")
TERMINAL_OR_WAITING = {
    "awaiting_profile_approval",
    "awaiting_connection_review",
    "ready_for_fulfillment",
    "blocked",
    "completed",
}


class OnboardingStepError(RuntimeError):
    def __init__(self, code: str, step: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.step = step
        self.retryable = retryable


def _latest_intake(database: Session, client_id: str) -> Optional[models.Intake]:
    return database.scalar(
        select(models.Intake)
        .where(models.Intake.client_id == client_id)
        .order_by(models.Intake.submitted_at.desc(), models.Intake.id.desc())
    )


def _job_for_run(database: Session, run_id: str) -> Optional[models.ScheduledJob]:
    return database.scalar(
        select(models.ScheduledJob).where(models.ScheduledJob.job_key == f"onboarding:{run_id}")
    )


def schedule_run(database: Session, run: models.OnboardingAutomationRun, *, immediate: bool = False) -> None:
    """Create or wake the persisted job without duplicating it."""
    due = datetime.utcnow() if immediate else datetime.utcnow() + timedelta(minutes=1)
    job = _job_for_run(database, run.id)
    if job is None:
        job = models.ScheduledJob(
            job_key=f"onboarding:{run.id}",
            job_type="onboarding_automation",
            client_id=run.client_id,
            interval_minutes=5,
            next_run_at=due,
        )
        database.add(job)
    else:
        job.enabled = True
        job.next_run_at = due
        job.last_error = None
    run.status = "queued"
    run.next_attempt_at = due
    database.flush()


def queue_onboarding_run(
    database: Session,
    client_id: str,
    intake_id: Optional[str] = None,
    *,
    immediate: bool = False,
) -> tuple[models.OnboardingAutomationRun, bool]:
    client = database.get(models.Client, client_id)
    if client is None:
        raise ValueError("client_not_found")
    if client.archived_at is not None or client.status == "archived":
        raise ValueError("archived_client")
    intake = database.get(models.Intake, intake_id) if intake_id else _latest_intake(database, client_id)
    if intake is None or intake.client_id != client_id:
        raise ValueError("intake_not_found")
    existing = database.scalar(
        select(models.OnboardingAutomationRun).where(
            models.OnboardingAutomationRun.intake_id == intake.id
        )
    )
    if existing is not None:
        if existing.status in {"blocked", "awaiting_connection_review"}:
            existing.last_error = None
            schedule_run(database, existing, immediate=immediate)
        return existing, True
    run = models.OnboardingAutomationRun(
        client_id=client_id,
        intake_id=intake.id,
        steps={step: {"status": "pending"} for step in STEPS},
    )
    database.add(run)
    database.flush()
    schedule_run(database, run, immediate=immediate)
    record_event(database, "onboarding_automation_queued", client_id=client_id, record_type="onboarding_run", record_id=run.id, details={"intake_id": intake.id})
    return run, False


def _set_step(run: models.OnboardingAutomationRun, step: str, status: str, **details) -> None:
    steps = dict(run.steps or {})
    steps[step] = {"status": status, **details}
    run.steps = steps
    run.current_step = step


def _hostname(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").lower().rstrip(".")


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _domain_key(value: str) -> str:
    host = _hostname(value)
    labels = [part for part in host.split(".") if part and part != "www"]
    return _key("".join(labels[:-1] if len(labels) > 1 else labels))


def _candidate(
    database: Session,
    run: models.OnboardingAutomationRun,
    provider: str,
    identifier: str,
    display_name: str,
    data: dict,
    evidence: dict,
) -> models.ConnectionCandidate:
    existing = database.scalar(
        select(models.ConnectionCandidate).where(
            models.ConnectionCandidate.run_id == run.id,
            models.ConnectionCandidate.provider == provider,
            models.ConnectionCandidate.external_identifier == identifier,
        )
    )
    if existing is not None:
        return existing
    item = models.ConnectionCandidate(
        run_id=run.id,
        client_id=run.client_id,
        provider=provider,
        external_identifier=identifier,
        display_name=display_name,
        connection_data=data,
        match_evidence=evidence,
        match_kind="uncertain",
    )
    database.add(item)
    database.flush()
    return item


def _interpret(database: Session, run: models.OnboardingAutomationRun, client: models.Client, intake: models.Intake) -> None:
    existing = database.scalar(
        select(models.InterpretationProposal).where(models.InterpretationProposal.intake_id == intake.id)
    )
    if existing is not None:
        _set_step(run, "interpretation", "completed", proposal_id=existing.id)
        return
    try:
        estimated_cost = max(0.0, float(os.getenv("OPENAI_INTERPRETATION_ESTIMATED_COST_USD", "0.05")))
    except ValueError:
        estimated_cost = 0.05
    try:
        ensure_budget(database, estimated_cost, datetime.utcnow())
        prompt_artifact, _ = compile_prompt(
            database,
            operation_key=f"prompt:openai-interpret:{intake.id}",
            client_id=client.id,
            intake_id=intake.id,
            purpose="onboarding_interpretation",
            model_role="balanced",
        )
        interpret_args = {
            "role": "balanced",
            "system_prompt": prompt_artifact.system_prompt,
            "user_prompt": prompt_artifact.user_prompt,
        }
        if "system_prompt" not in inspect.signature(openai_service.interpret).parameters:
            interpret_args = {"role": "balanced"}
        profile, missing, conflicts, processing_status = openai_service.interpret(
            intake, client.business_name, **interpret_args
        )
    except AIBudgetExceeded as error:
        raise OnboardingStepError(str(error), "interpretation") from error
    except openai_service.OpenAIInterpretationError as error:
        raise OnboardingStepError(error.code, "interpretation", retryable=error.retryable) from error
    proposal = models.InterpretationProposal(
        intake_id=intake.id,
        client_id=client.id,
        profile_data=profile,
        missing_information=missing,
        conflicting_information=conflicts,
        processing_status=processing_status,
        processed_at=datetime.utcnow(),
    )
    database.add(proposal)
    database.flush()
    database.add(
        models.ProfileVersion(
            source_proposal_id=proposal.id,
            intake_id=intake.id,
            client_id=client.id,
            version_number=1,
            profile_data=profile,
        )
    )
    record_usage(
        database,
        operation_key=f"openai-interpret:{intake.id}",
        client_id=client.id,
        task_id=None,
        provider="openai",
        model=openai_service.model_for_role("balanced"),
        model_role="balanced",
        operation="onboarding_interpretation",
        input_tokens=None,
        output_tokens=None,
        estimated_cost_usd=estimated_cost,
        actual_cost_usd=None,
    )
    _set_step(run, "interpretation", "completed", proposal_id=proposal.id, missing_information=missing, conflicting_information=conflicts)


def _connect_slack(database: Session, run: models.OnboardingAutomationRun) -> None:
    try:
        connection, _created = connect_client_channel(database, run.client_id)
    except SlackIntegrationError as error:
        raise OnboardingStepError(error.code, "slack", retryable=error.retryable) from error
    _set_step(run, "slack", "completed", connection_id=connection.id, channel_name=connection.channel_name)


def _project_data(project: VercelProject) -> dict:
    production = project.production_url or (project.production_domains[0] if project.production_domains else "")
    if production and not production.startswith("https://"):
        production = f"https://{production}"
    return {
        "external_project_id": project.project_id,
        "project_name": project.project_name,
        "production_url": production,
        "repository_url": project.repository_url,
    }


def _save_vercel(database: Session, client_id: str, project: VercelProject) -> models.WebsiteConnection:
    data = _project_data(project)
    conflict = database.scalar(
        select(models.WebsiteConnection).where(
            or_(
                models.WebsiteConnection.external_project_id == project.project_id,
                models.WebsiteConnection.project_name == project.project_name,
            ),
            models.WebsiteConnection.client_id != client_id,
        )
    )
    if conflict is not None:
        raise OnboardingStepError("vercel_project_already_assigned", "vercel")
    connection = models.WebsiteConnection(
        client_id=client_id,
        provider="vercel",
        external_project_id=data["external_project_id"],
        project_name=data["project_name"],
        production_url=data["production_url"],
        connection_status="connected",
        source="auto_discovery",
    )
    database.add(connection)
    database.flush()
    return connection


def _connect_vercel(database: Session, run: models.OnboardingAutomationRun, client: models.Client, intake: models.Intake) -> None:
    existing = database.scalar(select(models.WebsiteConnection).where(models.WebsiteConnection.client_id == client.id))
    if existing is not None:
        _set_step(run, "vercel", "completed", connection_id=existing.id)
        return
    try:
        projects = VercelAdapter().list_projects()
    except VercelIntegrationError as error:
        raise OnboardingStepError(error.code, "vercel", retryable=error.retryable) from error
    domain = _hostname(intake.domain)
    exact = [project for project in projects if domain in {_hostname(value) for value in project.production_domains if value}]
    if len(exact) == 1:
        connection = _save_vercel(database, client.id, exact[0])
        _set_step(run, "vercel", "completed", connection_id=connection.id, match="exact_domain")
        return
    likely = exact or [
        project for project in projects
        if _key(project.project_name) in {_key(client.business_name), _domain_key(intake.domain)}
        or _key(client.business_name) in _key(project.project_name)
    ]
    for project in likely:
        _candidate(database, run, "vercel", project.project_id, project.project_name, _project_data(project), {"client_domain": domain, "project_domains": list(project.production_domains), "reason": "multiple_exact_matches" if exact else "name_similarity"})
    _set_step(run, "vercel", "needs_review", candidate_count=len(likely), reason="no_unique_exact_domain_match")


def _repository_data(repository: GitHubRepository) -> dict:
    return {
        "repository_id": repository.repository_id,
        "owner": repository.owner,
        "repository_name": repository.name,
        "repository_url": repository.html_url,
        "default_branch": repository.default_branch,
        "private": repository.private,
    }


def _save_github(database: Session, client_id: str, repository: GitHubRepository) -> models.GitHubRepositoryConnection:
    conflict = database.scalar(
        select(models.GitHubRepositoryConnection).where(
            models.GitHubRepositoryConnection.repository_url == repository.html_url,
            models.GitHubRepositoryConnection.client_id != client_id,
        )
    )
    if conflict is not None:
        raise OnboardingStepError("github_repository_already_assigned", "github")
    connection = models.GitHubRepositoryConnection(
        client_id=client_id,
        owner=repository.owner,
        repository_name=repository.name,
        repository_url=repository.html_url,
        default_branch=repository.default_branch,
        connection_status="connected",
        source="github_app",
        last_checked_at=datetime.utcnow(),
        last_verified_at=datetime.utcnow(),
    )
    database.add(connection)
    database.flush()
    return connection


def _connect_github(database: Session, run: models.OnboardingAutomationRun, client: models.Client) -> None:
    existing = database.scalar(select(models.GitHubRepositoryConnection).where(models.GitHubRepositoryConnection.client_id == client.id))
    if existing is not None:
        _set_step(run, "github", "completed", connection_id=existing.id)
        return
    website = database.scalar(select(models.WebsiteConnection).where(models.WebsiteConnection.client_id == client.id))
    if website is None:
        _set_step(run, "github", "waiting", reason="vercel_connection_required")
        return
    try:
        adapter = GitHubAppAdapter()
        repositories = adapter.list_repositories()
        project = VercelAdapter().get_project(website.external_project_id)
    except GitHubIntegrationError as error:
        raise OnboardingStepError(error.code, "github", retryable=error.retryable) from error
    except VercelIntegrationError as error:
        raise OnboardingStepError(error.code, "github", retryable=error.retryable) from error
    expected_url = (project.repository_url or "").rstrip("/").casefold()
    exact = [item for item in repositories if item.html_url.rstrip("/").casefold() == expected_url] if expected_url else []
    if len(exact) == 1:
        connection = _save_github(database, client.id, exact[0])
        _set_step(run, "github", "completed", connection_id=connection.id, match="vercel_repository_link")
        return
    likely = exact or [item for item in repositories if _key(item.name) in {_key(website.project_name), _key(client.business_name)}]
    for repository in likely:
        _candidate(database, run, "github", repository.html_url, repository.name, _repository_data(repository), {"vercel_repository_url": project.repository_url, "vercel_project": website.project_name, "reason": "multiple_exact_matches" if exact else "name_similarity"})
    _set_step(run, "github", "needs_review", candidate_count=len(likely), reason="no_unique_vercel_repository_match")


def _save_analytics(database: Session, client_id: str, tracker_sites: list[str], source: str = "auto_discovery") -> models.WebsiteAnalyticsConnection:
    other_connections = list(
        database.scalars(
            select(models.WebsiteAnalyticsConnection).where(
                models.WebsiteAnalyticsConnection.client_id != client_id
            )
        )
    )
    if any(site in connection.tracker_sites for site in tracker_sites for connection in other_connections):
        raise OnboardingStepError("analytics_tracker_already_assigned", "website_analytics")
    connection = models.WebsiteAnalyticsConnection(
        client_id=client_id,
        tracker_sites=tracker_sites,
        connection_status="connected",
        source=source,
        last_checked_at=datetime.utcnow(),
    )
    database.add(connection)
    database.flush()
    return connection


def _analytics_rows() -> list[dict]:
    today = date.today()
    return fetch_summary(
        datetime.combine(today - timedelta(days=30), time.min, tzinfo=timezone.utc),
        datetime.combine(today, time.max, tzinfo=timezone.utc),
    )


def _connect_analytics(database: Session, run: models.OnboardingAutomationRun, intake: models.Intake) -> None:
    existing = database.scalar(select(models.WebsiteAnalyticsConnection).where(models.WebsiteAnalyticsConnection.client_id == run.client_id))
    if existing is not None:
        _set_step(run, "website_analytics", "completed", connection_id=existing.id, tracker_sites=existing.tracker_sites)
        return
    try:
        rows = _analytics_rows()
    except Exception as error:
        raise OnboardingStepError("website_analytics_temporarily_unavailable", "website_analytics", retryable=True) from error
    domain_key = _domain_key(intake.domain)
    sites = sorted({str(row.get("site", "")) for row in rows if row.get("site")})
    exact = [site for site in sites if _key(site) == domain_key]
    if len(exact) == 1:
        connection = _save_analytics(database, run.client_id, exact)
        _set_step(run, "website_analytics", "completed", connection_id=connection.id, match="exact_domain_key", tracker_sites=exact)
        return
    likely = exact or [site for site in sites if domain_key and (domain_key in _key(site) or _key(site) in domain_key)]
    for site in likely:
        _candidate(database, run, "website_analytics", site, site, {"tracker_sites": [site]}, {"client_domain_key": domain_key, "tracker_key": _key(site), "reason": "multiple_exact_matches" if exact else "partial_domain_match"})
    _set_step(run, "website_analytics", "needs_review", candidate_count=len(likely), reason="no_unique_exact_tracker_match")


def _pending_candidates(database: Session, run_id: str) -> int:
    return int(database.scalar(select(func.count()).select_from(models.ConnectionCandidate).where(models.ConnectionCandidate.run_id == run_id, models.ConnectionCandidate.status == "pending")) or 0)


def _create_workflow_tasks(database: Session, run: models.OnboardingAutomationRun, client: models.Client, intake: models.Intake, profile: models.OfficialProfile) -> list[str]:
    task_ids: list[str] = []
    for workflow in intake.enabled_workflows:
        key = _key(workflow)[:80] or "workflow"
        rule_key = f"onboarding_workflow:{key}"
        existing = database.scalar(
            select(models.Task).join(models.Finding, models.Finding.id == models.Task.source_finding_id).where(
                models.Task.client_id == client.id,
                models.Finding.rule_key == rule_key,
                models.Task.status.in_(["proposed", "approved", "blocked", "ready", "running", "completed", "verified"]),
            )
        )
        if existing is not None:
            task_ids.append(existing.id)
            continue
        finding = models.Finding(
            client_id=client.id,
            rule_key=rule_key,
            title=f"{workflow} workflow ready",
            explanation=f"The approved onboarding profile enables the {workflow} workflow.",
            evidence={"official_profile_id": profile.id, "intake_id": intake.id, "workflow": workflow},
            source="approved_onboarding",
            severity="medium",
            confidence="high",
            recommended_action=f"Review the proposed {workflow} fulfillment task.",
            status="open",
        )
        database.add(finding)
        database.flush()
        task = models.Task(
            client_id=client.id,
            source_finding_id=finding.id,
            title=f"Begin {workflow} fulfillment for {client.business_name}",
            requested_outcome=f"Start the approved {workflow} workflow using only verified client facts and connected services.",
            reason="Generated from an approved onboarding profile and enabled workflow.",
            estimated_effort="Estimate after task review",
            risk="high" if any(term in key for term in ("website", "googlebusiness", "publish")) else "medium",
            required_access=["approved client profile", "verified provider connections"],
            status="proposed",
        )
        database.add(task)
        database.flush()
        database.add(models.TaskStatusEvent(client_id=client.id, task_id=task.id, from_status=None, to_status="proposed", changed_by="onboarding automation", reason=f"Generated for enabled workflow: {workflow}"))
        notify_task_approval(database, task)
        task_ids.append(task.id)
    return task_ids


def _notify_blocked(database: Session, run: models.OnboardingAutomationRun, error: OnboardingStepError) -> None:
    deliver_notification(
        database,
        NotificationEvent(
            event_key=f"onboarding-blocked:{run.id}:{error.step}:{error.code}",
            client_id=run.client_id,
            category="missing_required_access",
            importance="high",
            explanation=f"Automatic onboarding stopped at {error.step}: {error.code}.",
            requested_action="Correct the provider configuration or connection, then resume onboarding.",
            related_record_type="onboarding_run",
            related_record_id=run.id,
        ),
    )


def process_onboarding_run(database: Session, run_id: str) -> models.OnboardingAutomationRun:
    run = database.get(models.OnboardingAutomationRun, run_id)
    if run is None:
        raise ValueError("onboarding_run_not_found")
    client = database.get(models.Client, run.client_id)
    intake = database.get(models.Intake, run.intake_id)
    if client is None or intake is None or intake.client_id != client.id:
        raise ValueError("onboarding_run_client_mismatch")
    if run.status == "completed":
        return run
    if client.archived_at is not None or client.status == "archived":
        run.status = "blocked"
        run.current_step = "archived"
        run.last_error = "archived_client"
        run.next_attempt_at = None
        database.commit()
        return run
    run.status = "running"
    run.started_at = run.started_at or datetime.utcnow()
    run.next_attempt_at = None
    run.attempt_count += 1
    run.last_error = None
    database.commit()
    try:
        _interpret(database, run, client, intake)
        database.commit()
        _connect_slack(database, run)
        database.commit()
        _connect_vercel(database, run, client, intake)
        database.commit()
        _connect_github(database, run, client)
        database.commit()
        _connect_analytics(database, run, intake)
        database.commit()
    except OnboardingStepError as error:
        database.rollback()
        run = database.get(models.OnboardingAutomationRun, run_id)
        run.current_step = error.step
        run.last_error = error.code
        _set_step(run, error.step, "retrying" if error.retryable and run.attempt_count < run.max_attempts else "blocked", error=error.code)
        if error.retryable and run.attempt_count < run.max_attempts:
            schedule_run(database, run)
        else:
            run.status = "blocked"
            run.next_attempt_at = None
            _notify_blocked(database, run, error)
        database.commit()
        return run

    if _pending_candidates(database, run.id):
        run.status = "awaiting_connection_review"
        run.current_step = "connection_review"
        run.next_attempt_at = None
        database.commit()
        return run
    incomplete_connections = [step for step in ("vercel", "github", "website_analytics") if (run.steps.get(step) or {}).get("status") != "completed"]
    if incomplete_connections:
        run.status = "blocked"
        run.current_step = incomplete_connections[0]
        run.last_error = f"{incomplete_connections[0]}_match_not_found"
        run.next_attempt_at = None
        _notify_blocked(database, run, OnboardingStepError(run.last_error, incomplete_connections[0]))
        database.commit()
        return run
    profile = database.scalar(select(models.OfficialProfile).where(models.OfficialProfile.client_id == client.id))
    approved_current_version = database.scalar(
        select(models.ProfileVersion.id).where(
            models.ProfileVersion.intake_id == intake.id,
            models.ProfileVersion.status == "approved",
            models.ProfileVersion.id == (profile.approved_version_id if profile else ""),
        )
    )
    if profile is None or approved_current_version is None:
        _set_step(run, "profile", "needs_review")
        run.status = "awaiting_profile_approval"
        run.current_step = "profile"
        run.next_attempt_at = None
        database.commit()
        return run
    _set_step(run, "profile", "completed", official_profile_id=profile.id)
    task_ids = _create_workflow_tasks(database, run, client, intake, profile)
    _set_step(run, "tasks", "completed", task_ids=task_ids)
    client.status = "ready_for_fulfillment"
    run.status = "completed"
    run.current_step = "completed"
    run.completed_at = datetime.utcnow()
    run.next_attempt_at = None
    record_event(database, "onboarding_automation_completed", client_id=client.id, record_type="onboarding_run", record_id=run.id, details={"task_ids": task_ids})
    database.commit()
    return run


def backfill_onboarding_runs(database: Session) -> tuple[list[str], list[str]]:
    queued: list[str] = []
    reused: list[str] = []
    clients = list(database.scalars(select(models.Client).where(models.Client.archived_at.is_(None))))
    for client in clients:
        intake = _latest_intake(database, client.id)
        if intake is None:
            continue
        _run, was_reused = queue_onboarding_run(database, client.id, intake.id)
        (reused if was_reused else queued).append(client.id)
    database.commit()
    return queued, reused
