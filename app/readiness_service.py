"""Value-free production readiness checks shared by HTTP and CLI surfaces."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
import os

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, text
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_service import auth_is_configured
from app import models
from app.config import read_database_url
from app.release_config import (
    billing_contract_valid,
    browser_worker_pair_valid,
    fulfillment_mode_valid,
    github_private_key_valid,
    https_origin,
    https_url,
    owner_emails_valid,
    positive_number,
    present,
)
from app.subscription_service import billing_enforcement_enabled, get_subscription, subscription_is_entitled


@dataclass(frozen=True)
class ReadinessCheck:
    key: str
    category: str
    status: str
    detail: str
    remediation: str | None = None

    def as_dict(self) -> dict:
        return {key: value for key, value in asdict(self).items() if value is not None}


def _result(
    key: str,
    category: str,
    valid: bool,
    passed: str,
    blocked: str,
    remediation: str,
) -> ReadinessCheck:
    return ReadinessCheck(
        key=key,
        category=category,
        status="passed" if valid else "blocked",
        detail=passed if valid else blocked,
        remediation=None if valid else remediation,
    )


def expected_migration_revision() -> str:
    config_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    config = AlembicConfig(str(config_path))
    config.set_main_option("script_location", str(config_path.parent / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head()


def current_migration_revision(database: Session) -> str | None:
    bind = database.get_bind()
    if "alembic_version" not in inspect(bind).get_table_names():
        return None
    return database.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()


def schema_contract_is_current(database: Session) -> bool:
    """Catch legacy tables that were stamped without receiving required columns."""
    inspector = inspect(database.get_bind())
    required = {
        "google_oauth_states": {"purpose", "nonce_hash", "redirect_path"},
        "reports": {"status", "approved_by", "approved_at", "client_share_issued_at", "client_share_revoked_at"},
        "prompt_artifacts": {"intake_id"},
        "report_deliveries": {"operation_key", "report_id", "status"},
        "codex_work_packets": {"handed_off_by", "handed_off_at", "result_execution_id"},
        "scheduled_jobs": {"last_started_at", "consecutive_failures", "last_duration_seconds", "parameters"},
        "client_subscriptions": {"client_id", "status", "plan", "provider", "current_period_end"},
        "subscription_events": {"event_id", "client_id", "payload_hash", "processed_at"},
        "website_previews": {"operation_key", "client_id", "task_id", "packet_id", "files", "file_manifest", "comparison", "technical_audit"},
        "tasks": {
            "browser_control_approved_by",
            "browser_control_approved_at",
            "browser_control_approval_reason",
            "expected_result",
            "success_metric",
            "verification_window",
        },
        "search_console_connections": {"last_query_rows", "last_page_rows", "last_query_start_date", "last_query_end_date"},
    }
    tables = set(inspector.get_table_names())
    for table, required_columns in required.items():
        if table not in tables:
            return False
        columns = {column["name"] for column in inspector.get_columns(table)}
        if not required_columns.issubset(columns):
            return False
    return True


def scheduler_contract_is_healthy(database: Session) -> bool:
    """Ensure enabled work is not silently wedged or repeatedly failing."""
    if "scheduled_jobs" not in inspect(database.get_bind()).get_table_names():
        # The schema check reports the migration blocker; do not turn readiness
        # into a 500 while an old database is being upgraded.
        return True
    now = datetime.utcnow()
    stale_running = database.scalar(
        select(models.ScheduledJob.id)
        .where(
            models.ScheduledJob.enabled.is_(True),
            models.ScheduledJob.last_status == "running",
            models.ScheduledJob.last_started_at.is_not(None),
            models.ScheduledJob.last_started_at < now - timedelta(minutes=30),
        )
        .limit(1)
    )
    repeatedly_failed = database.scalar(
        select(models.ScheduledJob.id)
        .where(
            models.ScheduledJob.enabled.is_(True),
            models.ScheduledJob.last_status == "failed",
            models.ScheduledJob.consecutive_failures >= 3,
        )
        .limit(1)
    )
    return stale_running is None and repeatedly_failed is None


def archived_client_jobs_are_disabled(database: Session) -> bool:
    """Archived clients must never retain an enabled fulfillment scheduler."""
    tables = set(inspect(database.get_bind()).get_table_names())
    if not {"scheduled_jobs", "clients"}.issubset(tables):
        return True
    record = database.scalar(
        select(models.ScheduledJob.id)
        .join(models.Client, models.Client.id == models.ScheduledJob.client_id)
        .where(
            models.ScheduledJob.enabled.is_(True),
            (models.Client.archived_at.is_not(None) | (models.Client.status == "archived")),
        )
        .limit(1)
    )
    return record is None


def integration_records_are_healthy(database: Session) -> bool:
    """Persisted provider errors must be visible before a release is called ready."""
    connection_models = (
        models.SlackChannelConnection,
        models.WebsiteConnection,
        models.GitHubRepositoryConnection,
        models.SearchConsoleConnection,
        models.GoogleBusinessProfileConnection,
    )
    unhealthy = {"error", "mismatch", "archive_pending"}
    tables = set(inspect(database.get_bind()).get_table_names())
    return all(
        connection_model.__tablename__ not in tables
        or
        database.scalar(
            select(connection_model.id)
            .where(connection_model.connection_status.in_(unhealthy))
            .limit(1)
        )
        is None
        for connection_model in connection_models
    )


def build_readiness(database: Session, profile: str = "core") -> dict:
    """Return actionable readiness facts without returning any configured value."""
    if profile not in {"core", "full"}:
        raise ValueError("unsupported_readiness_profile")

    database.execute(text("SELECT 1"))
    database_url = read_database_url()
    expected_revision = expected_migration_revision()
    current_revision = current_migration_revision(database)
    schema_current = schema_contract_is_current(database)
    checks = [
        _result(
            "database_persistence",
            "database",
            database_url.startswith(("postgresql://", "postgresql+psycopg://")),
            "Persistent PostgreSQL is configured.",
            "The deployment is not using PostgreSQL.",
            "Set MAX_DATABASE_URL to the production PostgreSQL connection URL.",
        ),
        _result(
            "database_migrations",
            "database",
            current_revision == expected_revision and schema_current,
            "The database revision and required schema are current.",
            "The database revision or required schema is missing or behind the application.",
            "Run alembic upgrade head against the deployment database.",
        ),
        _result(
            "owner_authentication",
            "security",
            auth_is_configured() and owner_emails_valid() and https_url("GOOGLE_REDIRECT_URI"),
            "Owner authentication is configured.",
            "Owner authentication is incomplete.",
            "Set AUTH_SECRET, allowed owner emails, and all Google OIDC callback values.",
        ),
        _result(
            "scheduled_job_authentication",
            "security",
            present("JOB_RUNNER_SECRET", "CRON_SECRET"),
            "Scheduled job endpoints have authentication secrets.",
            "One or more scheduled job secrets are missing.",
            "Set JOB_RUNNER_SECRET and CRON_SECRET.",
        ),
    ]

    if profile == "full":
        checks.extend(
            [
                _result(
                    "slack_delivery",
                    "provider",
                    present(
                        "SLACK_BOT_TOKEN",
                        "SLACK_SIGNING_SECRET",
                        "SLACK_WORKSPACE_ID",
                        "SLACK_OWNER_USER_IDS",
                    )
                    and https_origin("MAX_PUBLIC_BASE_URL"),
                    "Slack delivery and its public report origin are configured.",
                    "Slack delivery configuration is incomplete.",
                    "Set Slack credentials, workspace/owner IDs, and an HTTPS MAX_PUBLIC_BASE_URL origin.",
                ),
                _result(
                    "openai_budget",
                    "provider",
                    present("OPENAI_API_KEY") and positive_number("MONTHLY_AI_BUDGET_USD"),
                    "OpenAI access has an explicit monthly budget.",
                    "OpenAI access or its explicit monthly budget is missing.",
                    "Set OPENAI_API_KEY and MONTHLY_AI_BUDGET_USD before enabling AI work.",
                ),
                _result(
                    "fulfillment_mode",
                    "fulfillment",
                    fulfillment_mode_valid(),
                    "Fulfillment mode is explicitly selected: Codex handoff or approved GitHub/Vercel writes.",
                    "Fulfillment mode is missing or contradicts external-write configuration.",
                    "Set MAX_FULFILLMENT_MODE=codex_handoff with external writes disabled, or MAX_FULFILLMENT_MODE=github_vercel with MAX_ENABLE_EXTERNAL_WRITES=true.",
                ),
                _result(
                    "github_app",
                    "provider",
                    present(
                        "GITHUB_APP_ID",
                        "GITHUB_APP_INSTALLATION_ID",
                        "GITHUB_OWNER",
                        "GITHUB_REPOSITORY",
                    ) and github_private_key_valid(),
                    "GitHub App configuration is complete.",
                    "GitHub App configuration is incomplete.",
                    "Set the GitHub App identity, installation, owner, repository, and private key.",
                ),
                _result(
                    "vercel",
                    "provider",
                    present("VERCEL_API_TOKEN", "VERCEL_PROJECT_ID"),
                    "Vercel access is configured.",
                    "Vercel access is incomplete.",
                    "Set VERCEL_API_TOKEN and VERCEL_PROJECT_ID.",
                ),
                _result(
                    "google_business",
                    "provider",
                    present("GOOGLE_REFRESH_TOKEN", "GBP_ACCOUNT_ID", "GBP_LOCATION_ID"),
                    "Google Business access is configured.",
                    "Google Business access is incomplete.",
                    "Set the Google refresh token and verified GBP account/location IDs.",
                ),
                _result(
                    "browser_fallback",
                    "provider",
                    browser_worker_pair_valid(),
                    "Browser fallback is either fully configured or intentionally disabled.",
                    "Browser fallback is only partially configured.",
                    "Set both BROWSER_WORKER_URL and BROWSER_WORKER_TOKEN, or leave both unset.",
                ),
                _result(
                    "billing_contract",
                    "commercial",
                    billing_contract_valid(),
                    "Billing enforcement is either disabled or has a provider and signed webhook secret.",
                    "Paid-mode enforcement is enabled without a complete webhook contract.",
                    "Set BILLING_PROVIDER and BILLING_WEBHOOK_SECRET, or leave MAX_BILLING_ENFORCEMENT disabled.",
                ),
                _result(
                    "scheduler_operational_state",
                    "operations",
                    scheduler_contract_is_healthy(database),
                    "Enabled scheduled work is not stale or repeatedly failing.",
                    "One or more enabled jobs is stale or has repeatedly failed.",
                    "Inspect /health/details and the scheduled-jobs list, resolve the provider or worker error, then resume the job.",
                ),
                _result(
                    "archived_client_job_safety",
                    "safety",
                    archived_client_jobs_are_disabled(database),
                    "Archived clients have no enabled scheduled work.",
                    "An archived client still has enabled scheduled work.",
                    "Archive or disable every scheduled job belonging to the archived client before release.",
                ),
                _result(
                    "persisted_integration_health",
                    "operations",
                    integration_records_are_healthy(database),
                    "Persisted provider connections have no known error or mismatch state.",
                    "At least one persisted provider connection is in an error, mismatch, or archive-pending state.",
                    "Reconnect or reconcile the affected provider record, then rerun its verification before release.",
                ),
            ]
        )

    blocked = sum(check.status == "blocked" for check in checks)
    return {
        "status": "ready" if blocked == 0 else "not_ready",
        "profile": profile,
        "summary": {"passed": len(checks) - blocked, "blocked": blocked, "total": len(checks)},
        "checks": [check.as_dict() for check in checks],
    }


def build_client_launch_readiness(database: Session, client_id: str) -> dict:
    """Evaluate whether one client can safely enter recurring fulfillment.

    Global release readiness only proves that the deployment is configured. A
    client can still be missing an approved profile, a Slack boundary, or a
    website/provider connection. This gate keeps those two concerns separate
    and returns actionable, client-specific diagnostics without credentials.
    """
    client = database.get(models.Client, client_id)
    if client is None:
        raise ValueError("client_not_found")
    now = datetime.utcnow()
    required: list[ReadinessCheck] = []
    recommended: list[ReadinessCheck] = []

    def add(target: list[ReadinessCheck], key: str, valid: bool, passed: str, blocked: str, remediation: str) -> None:
        target.append(_result(key, "client", valid, passed, blocked, remediation))

    active = client.archived_at is None and client.status != "archived"
    add(required, "client_active", active, "Client is active.", "Client is archived and cannot receive fulfillment.", "Restore the client before starting work.")
    intake = database.scalar(
        select(models.Intake).where(models.Intake.client_id == client_id).order_by(models.Intake.submitted_at.desc(), models.Intake.id.desc())
    )
    add(required, "intake_received", intake is not None, "A client intake is saved.", "No client intake has been saved.", "Submit the onboarding intake before running fulfillment.")
    official = database.scalar(select(models.OfficialProfile.id).where(models.OfficialProfile.client_id == client_id))
    add(required, "official_profile_approved", official is not None, "An agency-approved official profile exists.", "The interpreted client profile has not been approved.", "Review and approve the latest profile version before fulfillment.")
    slack = database.scalar(select(models.SlackChannelConnection).where(models.SlackChannelConnection.client_id == client_id))
    slack_ok = slack is not None and slack.connection_status in {"connected", "connected_public"}
    add(required, "slack_boundary", slack_ok, "A verified Slack client channel is connected.", "No healthy Slack client channel is connected.", "Connect or repair the client Slack channel before sending client-scoped updates.")
    if billing_enforcement_enabled():
        subscription = get_subscription(database, client_id)
        paid_ok = subscription_is_entitled(subscription, now)
        add(required, "billing_entitlement", paid_ok, "The client has an active billing entitlement.", "The client has no active billing entitlement.", "Activate the subscription or disable paid-mode enforcement for a non-production environment.")
    else:
        add(recommended, "billing_entitlement", True, "Paid-mode enforcement is disabled in this environment.", "", "")

    workflows = {str(item).casefold() for item in (intake.enabled_workflows if intake else [])}
    website = database.scalar(select(models.WebsiteConnection).where(models.WebsiteConnection.client_id == client_id))
    website_ok = website is not None and website.connection_status in {"linked", "connected"}
    website_required = not workflows or bool(workflows & {"website", "seo", "local_seo", "content", "fulfillment", "website_generation"})
    add(required if website_required else recommended, "website_connection", website_ok, "A verified website connection is available.", "The client does not have a healthy website connection.", "Connect the production website or explicitly remove website-dependent work from the intake.")

    search_console = database.scalar(select(models.SearchConsoleConnection).where(models.SearchConsoleConnection.client_id == client_id))
    search_ok = search_console is not None and search_console.connection_status in {"linked", "connected"}
    add(recommended, "search_console", search_ok, "Search Console is connected for measurement.", "Search Console is not connected; SEO performance reporting will be limited.", "Connect and verify the correct Search Console property.")
    gbp = database.scalar(select(models.GoogleBusinessProfileConnection).where(models.GoogleBusinessProfileConnection.client_id == client_id))
    gbp_ok = gbp is not None and gbp.connection_status in {"connected", "linked"}
    add(recommended, "google_business_profile", gbp_ok, "Google Business Profile is connected.", "GBP evidence is unavailable; local-profile reporting and fulfillment will be limited.", "Connect and verify the correct GBP location.")
    github = database.scalar(select(models.GitHubRepositoryConnection).where(models.GitHubRepositoryConnection.client_id == client_id))
    github_required = fulfillment_mode_valid() and os.getenv("MAX_FULFILLMENT_MODE", "").strip().casefold() == "github_vercel"
    add(required if github_required else recommended, "github_repository", github is not None and github.connection_status in {"linked", "connected"}, "A scoped GitHub repository is connected.", "No healthy GitHub repository is connected for the selected write mode.", "Connect and verify the client repository before enabling GitHub/Vercel fulfillment.")

    run = database.scalar(select(models.OnboardingAutomationRun).where(models.OnboardingAutomationRun.client_id == client_id).order_by(models.OnboardingAutomationRun.created_at.desc(), models.OnboardingAutomationRun.id.desc()))
    run_ok = run is None or run.status in {"ready_for_fulfillment", "completed"}
    add(required, "onboarding_state", run_ok, "Onboarding is complete or has no blocked run.", "Onboarding is still blocked or awaiting a connection decision.", "Resolve the onboarding step shown in the client workspace, then rerun the readiness check.")

    configured_provider_count = sum(
        database.scalar(select(func.count()).select_from(model).where(model.client_id == client_id)) or 0
        for model in (
            models.SlackChannelConnection,
            models.WebsiteConnection,
            models.GitHubRepositoryConnection,
            models.SearchConsoleConnection,
            models.GoogleBusinessProfileConnection,
        )
    )
    recent_events = list(
        database.scalars(
            select(models.AuditEvent)
            .where(
                models.AuditEvent.client_id == client_id,
                models.AuditEvent.event_type == "client_provider_verification",
                models.AuditEvent.created_at >= now - timedelta(hours=24),
            )
            .order_by(models.AuditEvent.created_at.desc(), models.AuditEvent.id.desc())
        )
    )
    latest_provider_status: dict[str, str] = {}
    for event in recent_events:
        provider = str(event.details.get("provider") or "")
        if provider and provider not in latest_provider_status:
            latest_provider_status[provider] = str(event.details.get("status") or "failed")
    live_probe_ok = configured_provider_count == 0 or (
        len(latest_provider_status) >= configured_provider_count
        and all(status == "verified" for status in latest_provider_status.values())
    )
    add(
        recommended,
        "live_provider_verification",
        live_probe_ok,
        "Every configured provider has passed a live read-only probe in the last 24 hours.",
        "One or more configured providers has not passed a live probe in the last 24 hours.",
        "Run the client live provider checks, then resolve any returned provider code before fulfillment.",
    )

    required_blocked = sum(item.status == "blocked" for item in required)
    recommended_blocked = sum(item.status == "blocked" for item in recommended)
    return {
        "client": {"id": client.id, "business_name": client.business_name, "status": client.status},
        "status": "ready" if required_blocked == 0 else "blocked",
        "summary": {
            "required_passed": len(required) - required_blocked,
            "required_blocked": required_blocked,
            "recommended_passed": len(recommended) - recommended_blocked,
            "recommended_blocked": recommended_blocked,
            "total": len(required) + len(recommended),
        },
        "required_checks": [item.as_dict() for item in required],
        "recommended_checks": [item.as_dict() for item in recommended],
        "next_actions": [item.remediation for item in required + recommended if item.status == "blocked" and item.remediation],
        "generated_at": now.isoformat(),
    }
