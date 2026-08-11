"""Phase 20 tests for persisted, idempotent scheduled jobs."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app


def test_job_requires_valid_client_for_health_check() -> None:
    with TestClient(app) as client:
        response = client.post("/jobs", json={"job_key": "health-missing-client", "job_type": "health_check"})

    assert response.status_code == 422


def test_search_console_job_requires_client() -> None:
    with TestClient(app) as client:
        response = client.post("/jobs", json={"job_key": "search-console-missing-client", "job_type": "search_console_sync"})

    assert response.status_code == 422
    assert response.json()["detail"] == "search_console_sync requires client_id"


def test_daily_plan_job_persists_depth_focus_and_report_configuration() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/clients",
            json={"business_name": "Configured Planning Client", "service_start_date": "2026-08-05"},
        ).json()
        response = client.post(
            "/jobs",
            json={
                "job_key": "configured-daily-plan",
                "job_type": "daily_client_plan",
                "client_id": created["id"],
                "parameters": {
                    "depth": "in_depth",
                    "focus": "seo",
                    "create_report": True,
                    "report_type": "client",
                },
            },
        )

    assert response.status_code == 201
    assert response.json()["parameters"] == {
        "depth": "in_depth",
        "focus": "seo",
        "create_report": True,
        "create_tasks": False,
        "report_type": "client",
    }


def test_daily_plan_job_rejects_invalid_configuration() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/clients",
            json={"business_name": "Invalid Planning Client", "service_start_date": "2026-08-05"},
        ).json()
        response = client.post(
            "/jobs",
            json={
                "job_key": "invalid-daily-plan",
                "job_type": "daily_client_plan",
                "client_id": created["id"],
                "parameters": {"depth": "deep"},
            },
        )

    assert response.status_code == 422


def test_due_health_job_runs_once_until_next_interval(monkeypatch) -> None:
    monkeypatch.delenv("JOB_RUNNER_SECRET", raising=False)
    with TestClient(app) as client:
        created = client.post(
            "/clients",
            json={"business_name": "Scheduled Health Client", "service_start_date": "2026-08-05"},
        ).json()
        job = client.post(
            "/jobs",
            json={
                "job_key": "scheduled-health-client",
                "job_type": "health_check",
                "client_id": created["id"],
                "interval_minutes": 60,
                "next_run_at": (datetime.utcnow() - timedelta(minutes=1)).isoformat(),
            },
        )
        first = client.post("/jobs/run-due")
        second = client.post("/jobs/run-due")

    assert job.status_code == 201
    assert first.json()[0]["status"] == "completed"
    assert second.json() == []


def test_job_runner_secret_rejects_unauthorized_calls(monkeypatch) -> None:
    monkeypatch.setenv("JOB_RUNNER_SECRET", "scheduler-secret")
    with TestClient(app) as client:
        missing = client.post("/jobs/run-due")
        wrong = client.post("/jobs/run-due", headers={"X-Max-Job-Secret": "wrong"})
        allowed = client.post("/jobs/run-due", headers={"X-Max-Job-Secret": "scheduler-secret"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert allowed.status_code == 200


def test_provider_health_sweep_requires_scheduler_secret_and_returns_safe_summary(monkeypatch) -> None:
    monkeypatch.setenv("JOB_RUNNER_SECRET", "scheduler-secret")
    monkeypatch.setattr(
        "app.client_provider_verification.sweep_active_clients",
        lambda database: {"status": "verified", "clients": []},
    )
    with TestClient(app) as client:
        missing = client.get("/jobs/provider-health")
        allowed = client.get("/jobs/provider-health", headers={"X-Max-Job-Secret": "scheduler-secret"})

    assert missing.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json() == {"status": "verified", "clients": []}


def test_post_scheduler_fails_closed_in_production_when_secret_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("JOB_RUNNER_SECRET", raising=False)
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.setenv("VERCEL_ENV", "production")
    with TestClient(app) as client:
        response = client.post("/jobs/run-due")

    assert response.status_code == 401


def test_vercel_cron_get_requires_bearer_secret(monkeypatch) -> None:
    monkeypatch.delenv("JOB_RUNNER_SECRET", raising=False)
    monkeypatch.setenv("CRON_SECRET", "vercel-cron-secret")
    with TestClient(app) as client:
        missing = client.get("/jobs/run-due")
        wrong = client.get("/jobs/run-due", headers={"Authorization": "Bearer wrong"})
        allowed = client.get(
            "/jobs/run-due",
            headers={"Authorization": "Bearer vercel-cron-secret"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert allowed.status_code == 200


def test_vercel_cron_get_never_runs_without_a_configured_secret(monkeypatch) -> None:
    monkeypatch.delenv("JOB_RUNNER_SECRET", raising=False)
    monkeypatch.delenv("CRON_SECRET", raising=False)
    with TestClient(app) as client:
        response = client.get("/jobs/run-due")

    assert response.status_code == 401


def test_migration_job_requires_secret_and_returns_only_revision_state(monkeypatch) -> None:
    monkeypatch.setenv("JOB_RUNNER_SECRET", "migration-secret")
    monkeypatch.setattr(
        "app.routes.jobs.run_production_migrations",
        lambda: {"status": "current", "revision": "0006_google_oauth_state_context"},
    )
    with TestClient(app) as client:
        missing = client.post("/jobs/migrate")
        wrong = client.post("/jobs/migrate", headers={"X-Max-Job-Secret": "wrong"})
        allowed = client.post(
            "/jobs/migrate", headers={"X-Max-Job-Secret": "migration-secret"}
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json() == {
        "status": "current",
        "revision": "0006_google_oauth_state_context",
    }
    assert "url" not in str(allowed.json()).casefold()


def test_duplicate_job_key_is_rejected() -> None:
    with TestClient(app) as client:
        payload = {"job_key": "duplicate-job-key", "job_type": "website_metrics_sync"}
        first = client.post("/jobs", json=payload)
        second = client.post("/jobs", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409


def test_unknown_client_job_is_rejected() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/jobs",
            json={"job_key": "unknown-health-client", "job_type": "health_check", "client_id": "client_missing"},
        )

    assert response.status_code == 404


def test_due_search_console_job_uses_rolling_28_day_window(monkeypatch) -> None:
    from app.google_search_console_service import SearchConsoleMetrics
    from tests.test_search_console import client_with_domain

    class FakeSearchConsole:
        def read_metrics(self, _property_url, start_date, end_date):
            assert (end_date, start_date) == ("2026-08-10", "2026-07-13")
            return SearchConsoleMetrics(clicks=22, impressions=220)

    now = datetime(2026, 8, 10, 9, 0, 0)
    with TestClient(app) as client:
        client_id, domain = client_with_domain(client, "scheduled-search-console")
        assert client.post(
            f"/clients/{client_id}/search-console", json={"property_url": f"sc-domain:{domain}"}
        ).status_code == 201
        created = client.post(
            "/jobs",
            json={
                "job_key": "scheduled-search-console",
                "job_type": "search_console_sync",
                "client_id": client_id,
                "next_run_at": (now - timedelta(minutes=1)).isoformat(),
            },
        )
        monkeypatch.setattr("app.routes.search_console.GoogleSearchConsoleAdapter", FakeSearchConsole)
        from app.database import SessionLocal
        from app.job_service import run_due_jobs

        with SessionLocal() as database:
            results = run_due_jobs(database, now=now)
        metrics = client.get(f"/clients/{client_id}/metrics")

    assert created.status_code == 201
    assert results == [{"job_id": created.json()["id"], "job_key": "scheduled-search-console", "status": "completed", "error": None}]
    assert {item["metric_name"] for item in metrics.json()} == {"search_clicks", "impressions"}


def test_failed_client_job_uses_backoff_and_creates_actionable_notification(monkeypatch) -> None:
    from datetime import datetime
    from sqlalchemy import select
    from app import models
    from app.database import SessionLocal

    monkeypatch.delenv("JOB_RUNNER_SECRET", raising=False)
    monkeypatch.delenv("CRON_SECRET", raising=False)
    with TestClient(app) as client:
        created = client.post(
            "/clients",
            json={"business_name": "Scheduled Failure Client", "service_start_date": "2026-08-05"},
        ).json()
        job = client.post(
            "/jobs",
            json={
                "job_key": "scheduled-failure-client",
                "job_type": "health_check",
                "client_id": created["id"],
                "interval_minutes": 60,
                "next_run_at": (datetime.utcnow() - timedelta(minutes=1)).isoformat(),
            },
        ).json()
        monkeypatch.setattr(
            "app.routes.health_checks.run_health_check",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
        )
        result = client.post("/jobs/run-due")
        assert result.status_code == 200, result.text
        saved_jobs = client.get("/jobs").json()
        notifications = client.get(f"/notifications?client_id={created['id']}")

    saved = next(item for item in saved_jobs if item["id"] == job["id"])
    assert result.json()[0]["status"] == "failed"
    assert saved["consecutive_failures"] == 1
    assert saved["last_duration_seconds"] is not None
    assert saved["next_run_at"] > job["next_run_at"]
    assert any(item["category"] == "scheduled_job_failure" for item in notifications.json())
