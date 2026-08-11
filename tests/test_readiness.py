"""Launch readiness is actionable, value-free, and shared by HTTP and CLI."""

import importlib
from datetime import date, datetime, timedelta

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app import models
from app.database import SessionLocal, create_database
from app.main import app
from app.readiness_service import (
    archived_client_jobs_are_disabled,
    build_client_launch_readiness,
    build_readiness,
    current_migration_revision,
    scheduler_contract_is_healthy,
)


def test_client_launch_readiness_reports_missing_inputs_and_never_exposes_secrets() -> None:
    create_database()
    with SessionLocal() as database:
        client = models.Client(business_name="Client launch gate", service_start_date=date.today())
        database.add(client)
        database.commit()
        client_id = client.id
        result = build_client_launch_readiness(database, client_id)

    assert result["status"] == "blocked"
    keys = {check["key"] for check in result["required_checks"]}
    assert {"intake_received", "official_profile_approved", "slack_boundary", "website_connection"}.issubset(keys)
    assert result["next_actions"]
    assert "secret" not in str(result).casefold()

    with TestClient(app) as api:
        response = api.get(f"/clients/{client_id}/launch-readiness")
        missing = api.get("/clients/client_does_not_exist/launch-readiness")
    assert response.status_code == 200
    assert response.json()["client"]["id"] == client_id
    assert missing.status_code == 404
from scripts import check_launch_readiness


def _set_ready_environment(monkeypatch) -> None:
    values = {
        "MAX_DATABASE_URL": "postgresql://user:password@database.example.test/max",
        "AUTH_SECRET": "auth-secret-value",
        "MAX_ALLOWED_GOOGLE_EMAILS": "owner@example.test",
        "GOOGLE_CLIENT_ID": "google-client-id",
        "GOOGLE_CLIENT_SECRET": "google-secret-value",
        "GOOGLE_REDIRECT_URI": "https://max.example.test/auth/google/callback",
        "JOB_RUNNER_SECRET": "runner-secret-value",
        "CRON_SECRET": "cron-secret-value",
        "SLACK_BOT_TOKEN": "slack-secret-value",
        "SLACK_SIGNING_SECRET": "slack-signing-value",
        "SLACK_WORKSPACE_ID": "T_MAX",
        "SLACK_OWNER_USER_IDS": "U_OWNER",
        "MAX_PUBLIC_BASE_URL": "https://max.example.test",
        "OPENAI_API_KEY": "openai-secret-value",
        "MONTHLY_AI_BUDGET_USD": "50",
        "GITHUB_APP_ID": "github-app-id",
        "GITHUB_APP_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----\\ngithub-secret-value\\n-----END PRIVATE KEY-----",
        "GITHUB_APP_INSTALLATION_ID": "github-installation-id",
        "GITHUB_OWNER": "owner",
        "GITHUB_REPOSITORY": "repo",
        "VERCEL_API_TOKEN": "vercel-secret-value",
        "VERCEL_PROJECT_ID": "vercel-project-id",
        "GOOGLE_REFRESH_TOKEN": "google-refresh-secret-value",
        "GBP_ACCOUNT_ID": "gbp-account-id",
        "GBP_LOCATION_ID": "gbp-location-id",
        "MAX_FULFILLMENT_MODE": "codex_handoff",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("BROWSER_WORKER_URL", raising=False)
    monkeypatch.delenv("BROWSER_WORKER_TOKEN", raising=False)


def test_local_readiness_reports_actionable_database_blockers_without_values() -> None:
    with TestClient(app) as client:
        response = client.get("/health/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["profile"] == "core"
    checks = {check["key"]: check for check in body["checks"]}
    assert checks["database_persistence"]["status"] == "blocked"
    assert checks["database_migrations"]["status"] == "blocked"
    assert "remediation" in checks["database_migrations"]
    assert "sqlite" not in str(body).casefold()


def test_full_readiness_can_pass_without_exposing_provider_values(monkeypatch) -> None:
    _set_ready_environment(monkeypatch)
    monkeypatch.setattr("app.readiness_service.expected_migration_revision", lambda: "head_revision")
    monkeypatch.setattr("app.readiness_service.current_migration_revision", lambda database: "head_revision")
    monkeypatch.setattr("app.readiness_service.scheduler_contract_is_healthy", lambda database: True)
    monkeypatch.setattr("app.readiness_service.archived_client_jobs_are_disabled", lambda database: True)
    monkeypatch.setattr("app.readiness_service.integration_records_are_healthy", lambda database: True)

    with SessionLocal() as database:
        result = build_readiness(database, "full")

    assert result["status"] == "ready"
    assert result["summary"] == {"passed": 15, "blocked": 0, "total": 15}
    rendered = str(result)
    for secret in (
        "auth-secret-value",
        "slack-secret-value",
        "openai-secret-value",
        "github-secret-value",
        "vercel-secret-value",
        "google-refresh-secret-value",
    ):
        assert secret not in rendered


def test_partial_browser_worker_configuration_blocks_full_readiness(monkeypatch) -> None:
    _set_ready_environment(monkeypatch)
    monkeypatch.setenv("BROWSER_WORKER_URL", "https://worker.example.test")
    monkeypatch.delenv("BROWSER_WORKER_TOKEN", raising=False)
    monkeypatch.setattr("app.readiness_service.expected_migration_revision", lambda: "head_revision")
    monkeypatch.setattr("app.readiness_service.current_migration_revision", lambda database: "head_revision")

    with SessionLocal() as database:
        result = build_readiness(database, "full")

    browser = next(check for check in result["checks"] if check["key"] == "browser_fallback")
    assert result["status"] == "not_ready"
    assert browser["status"] == "blocked"
    assert "https://worker.example.test" not in str(result)


def test_full_readiness_blocks_stale_or_repeatedly_failed_scheduler_jobs(monkeypatch) -> None:
    _set_ready_environment(monkeypatch)
    monkeypatch.setattr("app.readiness_service.expected_migration_revision", lambda: "head_revision")
    monkeypatch.setattr("app.readiness_service.current_migration_revision", lambda database: "head_revision")
    monkeypatch.setattr("app.readiness_service.scheduler_contract_is_healthy", lambda database: False)

    with SessionLocal() as database:
        result = build_readiness(database, "full")

    checks = {check["key"]: check for check in result["checks"]}
    assert result["status"] == "not_ready"
    assert checks["scheduler_operational_state"]["status"] == "blocked"
    assert "provider or worker" in checks["scheduler_operational_state"]["remediation"]


def test_full_readiness_blocks_known_persisted_integration_errors(monkeypatch) -> None:
    _set_ready_environment(monkeypatch)
    monkeypatch.setattr("app.readiness_service.expected_migration_revision", lambda: "head_revision")
    monkeypatch.setattr("app.readiness_service.current_migration_revision", lambda database: "head_revision")
    monkeypatch.setattr("app.readiness_service.integration_records_are_healthy", lambda database: False)

    with SessionLocal() as database:
        result = build_readiness(database, "full")

    checks = {check["key"]: check for check in result["checks"]}
    assert result["status"] == "not_ready"
    assert checks["persisted_integration_health"]["status"] == "blocked"


def test_scheduler_readiness_detects_a_stale_running_job() -> None:
    create_database()
    with SessionLocal() as database:
        job = models.ScheduledJob(
            job_key="readiness-stale-job",
            job_type="daily_client_plan",
            interval_minutes=60,
            next_run_at=datetime.utcnow(),
            last_status="running",
            last_started_at=datetime.utcnow() - timedelta(hours=1),
        )
        database.add(job)
        database.flush()
        assert scheduler_contract_is_healthy(database) is False
        database.rollback()


def test_archived_client_readiness_detects_enabled_job() -> None:
    create_database()
    with SessionLocal() as database:
        client = models.Client(
            business_name="Readiness archived client",
            service_start_date=date.today(),
            status="archived",
            archived_at=datetime.utcnow(),
        )
        database.add(client)
        database.flush()
        database.add(
            models.ScheduledJob(
                job_key="readiness-archived-job",
                job_type="daily_client_plan",
                client_id=client.id,
                interval_minutes=60,
                next_run_at=datetime.utcnow(),
                enabled=True,
            )
        )
        database.flush()
        assert archived_client_jobs_are_disabled(database) is False
        database.rollback()


def test_full_readiness_rejects_malformed_release_credential_shapes(monkeypatch) -> None:
    _set_ready_environment(monkeypatch)
    monkeypatch.setenv("MAX_ALLOWED_GOOGLE_EMAILS", "not-an-email")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "not-a-pem-key")
    monkeypatch.setenv("BROWSER_WORKER_URL", "http://worker.example.test")
    monkeypatch.setenv("BROWSER_WORKER_TOKEN", "worker-token")
    monkeypatch.setattr("app.readiness_service.expected_migration_revision", lambda: "head_revision")
    monkeypatch.setattr("app.readiness_service.current_migration_revision", lambda database: "head_revision")

    with SessionLocal() as database:
        result = build_readiness(database, "full")

    checks = {check["key"]: check for check in result["checks"]}
    assert result["status"] == "not_ready"
    assert checks["owner_authentication"]["status"] == "blocked"
    assert checks["github_app"]["status"] == "blocked"
    assert checks["browser_fallback"]["status"] == "blocked"


def test_create_all_database_is_not_mistaken_for_migrated_database() -> None:
    with SessionLocal() as database:
        assert current_migration_revision(database) is None


def test_readiness_rejects_unknown_profile() -> None:
    with TestClient(app) as client:
        response = client.get("/health/readiness?profile=secrets")

    assert response.status_code == 422
    assert response.json()["detail"] == "unsupported_readiness_profile"


def test_launch_readiness_cli_returns_failure_for_blockers_and_success_when_ready(
    monkeypatch, capsys
) -> None:
    blocked = {
        "status": "not_ready",
        "profile": "core",
        "summary": {"passed": 0, "blocked": 1, "total": 1},
        "checks": [
            {
                "key": "database_migrations",
                "status": "blocked",
                "detail": "The schema is behind.",
                "remediation": "Run alembic upgrade head.",
            }
        ],
    }
    monkeypatch.setattr(check_launch_readiness, "build_readiness", lambda database, profile: blocked)
    assert check_launch_readiness.main([]) == 1
    assert "Run alembic upgrade head" in capsys.readouterr().out

    ready = {
        "status": "ready",
        "profile": "full",
        "summary": {"passed": 1, "blocked": 0, "total": 1},
        "checks": [
            {"key": "database_migrations", "status": "passed", "detail": "Schema current."}
        ],
    }
    monkeypatch.setattr(check_launch_readiness, "build_readiness", lambda database, profile: ready)
    assert check_launch_readiness.main(["--profile", "full"]) == 0
    assert "1 passed, 0 blocked" in capsys.readouterr().out


def test_launch_readiness_live_slack_runs_only_after_static_gate(monkeypatch, capsys) -> None:
    ready = {
        "status": "ready",
        "profile": "full",
        "summary": {"passed": 1, "blocked": 0, "total": 1},
        "checks": [{"key": "database_migrations", "status": "passed", "detail": "Schema current."}],
    }
    monkeypatch.setattr(check_launch_readiness, "build_readiness", lambda database, profile: ready)
    calls = []
    monkeypatch.setattr(check_launch_readiness.check_slack_provider, "main", lambda: calls.append(True) or 0)
    assert check_launch_readiness.main(["--profile", "full", "--live-slack"]) == 0
    assert calls == [True]
    assert "Live Slack provider verification" in capsys.readouterr().out


def test_launch_readiness_live_slack_requires_full_profile(capsys) -> None:
    assert check_launch_readiness.main(["--live-slack"]) == 1
    assert "require --profile full" in capsys.readouterr().err


def test_launch_readiness_live_providers_runs_after_static_gate(monkeypatch) -> None:
    ready = {
        "status": "ready",
        "profile": "full",
        "summary": {"passed": 1, "blocked": 0, "total": 1},
        "checks": [{"key": "database_migrations", "status": "passed", "detail": "Schema current."}],
    }
    monkeypatch.setattr(check_launch_readiness, "build_readiness", lambda database, profile: ready)
    calls = []
    monkeypatch.setattr(check_launch_readiness.check_provider_connections, "main", lambda: calls.append(True) or 0)
    assert check_launch_readiness.main(["--profile", "full", "--live-providers"]) == 0
    assert calls == [True]


def test_google_oauth_context_migration_repairs_legacy_table(monkeypatch) -> None:
    migration = importlib.import_module(
        "migrations.versions.0006_google_oauth_state_context"
    )
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE google_oauth_states ("
                "id VARCHAR(32) PRIMARY KEY, state_hash VARCHAR(128) NOT NULL, "
                "scopes VARCHAR(1000) NOT NULL)"
            )
        )
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        migration.upgrade()

        columns = {column["name"]: column for column in inspect(connection).get_columns("google_oauth_states")}

    assert {"purpose", "nonce_hash", "redirect_path"}.issubset(columns)
    assert columns["purpose"]["nullable"] is False


def test_agency_ai_usage_migration_allows_no_client(monkeypatch) -> None:
    migration = importlib.import_module("migrations.versions.0007_agency_ai_usage")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE clients (id VARCHAR(16) PRIMARY KEY)"))
        connection.execute(
            text(
                "CREATE TABLE ai_usage_records ("
                "id VARCHAR(32) PRIMARY KEY, client_id VARCHAR(32) NOT NULL, "
                "FOREIGN KEY(client_id) REFERENCES clients(id))"
            )
        )
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        migration.upgrade()

        columns = {
            column["name"]: column
            for column in inspect(connection).get_columns("ai_usage_records")
        }

    assert columns["client_id"]["nullable"] is True
