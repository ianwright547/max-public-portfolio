"""Automatic onboarding stays durable, client-scoped, and approval-gated."""

from datetime import datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.database import SessionLocal
from app.github_service import GitHubRepository
from app.main import app
from app.onboarding_automation import process_onboarding_run
from app.slack_service import SlackChannel, SlackMessage, SlackWorkspace
from app.vercel_service import VercelProject
from tests.test_intakes import make_intake_payload


class FakeSlack:
    created = 0

    def verify_workspace(self):
        return SlackWorkspace("T_AUTO", "Agency", "U_BOT")

    def create_public_channel(self, channel_name):
        type(self).created += 1
        return SlackChannel(f"C_AUTO_{type(self).created}", channel_name)

    def create_private_channel(self, channel_name):
        raise AssertionError("Automatic onboarding must create public channels")

    def invite_users(self, channel_id, user_ids):
        return None

    def post_message(self, channel_id, text, operation_key):
        return SlackMessage(channel_id, "1.0")


def create_client_and_intake(client: TestClient, name: str, domain: str = "example.com") -> tuple[str, str, str]:
    client_id = client.post(
        "/clients", json={"business_name": name, "service_start_date": "2026-08-13"}
    ).json()["id"]
    payload = make_intake_payload()
    payload["domain"] = domain
    intake = client.post(f"/clients/{client_id}/intakes", json=payload).json()
    run = client.get(f"/clients/{client_id}/onboarding-automation").json()
    return client_id, intake["id"], run["id"]


def patch_happy_providers(monkeypatch, domain="example.com"):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("SLACK_WORKSPACE_ID", "T_AUTO")
    monkeypatch.setenv("VERCEL_API_TOKEN", "test")
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "test")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "2")
    monkeypatch.setattr(
        "app.onboarding_automation.openai_service.interpret",
        lambda intake, business_name, role: (
            {"business_name": business_name, "domain": intake.domain, "enabled_workflows": intake.enabled_workflows},
            [],
            [],
            "ready_for_review",
        ),
    )
    monkeypatch.setattr("app.onboarding_automation.connect_client_channel", lambda database, client_id: __import__("app.slack_service", fromlist=["connect_client_channel"]).connect_client_channel(database, client_id, FakeSlack()))
    resource_key = domain.replace(".", "-")
    tracker_key = domain.replace(".", "").replace("www", "")[:-3] if domain.endswith(".com") else domain.replace(".", "")
    project = VercelProject(
        f"prj_{resource_key}",
        f"{resource_key}-site",
        domain,
        "available",
        (domain,),
        f"https://github.com/agency/{resource_key}-site",
    )
    monkeypatch.setattr("app.onboarding_automation.VercelAdapter.list_projects", lambda self: [project])
    monkeypatch.setattr("app.onboarding_automation.VercelAdapter.get_project", lambda self, project_id: project)
    repository = GitHubRepository(resource_key, "agency", f"{resource_key}-site", f"https://github.com/agency/{resource_key}-site", "main", True)
    monkeypatch.setattr("app.onboarding_automation.GitHubAppAdapter.list_repositories", lambda self: [repository])
    monkeypatch.setattr(
        "app.onboarding_automation._analytics_rows",
        lambda: [{"site": tracker_key, "unique_visitors": 1, "pageviews": 1, "call_clicks": 0, "form_submits": 0}],
    )


def test_intake_queues_exactly_one_durable_run_and_job() -> None:
    with TestClient(app) as client:
        client_id, intake_id, run_id = create_client_and_intake(client, "Queued Automation")
        resumed = client.post(f"/clients/{client_id}/onboarding-automation")
        runs = client.get(f"/clients/{client_id}/onboarding-automation")

    assert resumed.status_code == 202
    assert resumed.json()["id"] == run_id
    assert runs.json()["intake_id"] == intake_id
    with SessionLocal() as database:
        jobs = list(database.scalars(select(models.ScheduledJob).where(models.ScheduledJob.job_key == f"onboarding:{run_id}")))
    assert len(jobs) == 1


def test_archived_client_cannot_start_or_resume_onboarding() -> None:
    with TestClient(app) as client:
        client_id, _intake_id, run_id = create_client_and_intake(client, f"Archived Onboarding {uuid4().hex[:8]}")
        archived = client.post(f"/clients/{client_id}/archive")
        resumed = client.post(f"/clients/{client_id}/onboarding-automation")

    assert archived.status_code == 200
    assert resumed.status_code == 409
    with SessionLocal() as database:
        processed = process_onboarding_run(database, run_id)
        processed_status = processed.status
        processed_error = processed.last_error
    assert processed_status == "blocked"
    assert processed_error == "archived_client"


def test_exact_provider_matches_connect_then_wait_for_profile_approval(monkeypatch) -> None:
    patch_happy_providers(monkeypatch, "exact-auto.com")
    with TestClient(app) as client:
        client_id, _intake_id, run_id = create_client_and_intake(client, "Exact Automation", "exact-auto.com")
    with SessionLocal() as database:
        run = process_onboarding_run(database, run_id)
        run_status = run.status
        website = database.scalar(select(models.WebsiteConnection).where(models.WebsiteConnection.client_id == client_id))
        github = database.scalar(select(models.GitHubRepositoryConnection).where(models.GitHubRepositoryConnection.client_id == client_id))
        analytics = database.scalar(select(models.WebsiteAnalyticsConnection).where(models.WebsiteAnalyticsConnection.client_id == client_id))
        slack = database.scalar(select(models.SlackChannelConnection).where(models.SlackChannelConnection.client_id == client_id))

    assert run_status == "awaiting_profile_approval"
    assert website.external_project_id == "prj_exact-auto-com"
    assert github.repository_url == "https://github.com/agency/exact-auto-com-site"
    assert analytics.tracker_sites == ["exact-auto"]
    assert slack.connection_status == "connected_public"


def test_ambiguous_vercel_match_waits_for_owner_and_approval_rechecks(monkeypatch) -> None:
    patch_happy_providers(monkeypatch, "ambiguous-auto.com")
    projects = [
        VercelProject("prj_ambiguous_first", "first", "ambiguous-auto.com", "available", ("ambiguous-auto.com",)),
        VercelProject("prj_ambiguous_second", "second", "ambiguous-auto.com", "available", ("ambiguous-auto.com",)),
    ]
    monkeypatch.setattr("app.onboarding_automation.VercelAdapter.list_projects", lambda self: projects)
    monkeypatch.setattr("app.routes.onboarding_automation.VercelAdapter.get_project", lambda self, project_id: next(item for item in projects if item.project_id == project_id))
    with TestClient(app) as client:
        client_id, _intake_id, run_id = create_client_and_intake(client, "Ambiguous Automation", "ambiguous-auto.com")
    with SessionLocal() as database:
        run = process_onboarding_run(database, run_id)
        run_status = run.status
    with TestClient(app) as client:
        candidates = client.get(f"/clients/{client_id}/connection-candidates").json()
        approved = client.post(
            f"/connection-candidates/{candidates[0]['id']}/decision",
            json={"decision": "approve", "decided_by": "Agency Owner"},
        )

    assert run_status == "awaiting_connection_review"
    assert len(candidates) == 2
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    with TestClient(app) as client:
        decided = client.get(f"/clients/{client_id}/connection-candidates").json()
    assert {item["status"] for item in decided} == {"approved", "rejected"}


def test_existing_verified_mapping_survives_backfill() -> None:
    with TestClient(app) as client:
        client_id, _intake_id, run_id = create_client_and_intake(client, "Backfill Automation")
    with SessionLocal() as database:
        database.add(models.WebsiteConnection(client_id=client_id, provider="vercel", external_project_id="prj_verified", project_name="verified", production_url="https://verified.example.com", connection_status="connected", source="confirmed_vercel_import"))
        database.commit()
    with TestClient(app) as client:
        first = client.post("/onboarding-automation/backfill")
        second = client.post("/onboarding-automation/backfill")
    with SessionLocal() as database:
        website = database.scalar(select(models.WebsiteConnection).where(models.WebsiteConnection.client_id == client_id))
        run_count = database.scalar(select(__import__("sqlalchemy").func.count()).select_from(models.OnboardingAutomationRun).where(models.OnboardingAutomationRun.client_id == client_id))

    assert first.status_code == 202
    assert client_id in second.json()["reused_client_ids"]
    assert website.external_project_id == "prj_verified"
    assert run_count == 1


def test_profile_approval_resumes_and_generates_enabled_workflow_tasks(monkeypatch) -> None:
    patch_happy_providers(monkeypatch, "handoff-auto.com")
    with TestClient(app) as client:
        client_id, _intake_id, run_id = create_client_and_intake(client, "Handoff Automation", "handoff-auto.com")
    with SessionLocal() as database:
        process_onboarding_run(database, run_id)
        version = database.scalar(select(models.ProfileVersion).where(models.ProfileVersion.client_id == client_id))
        version_id = version.id
    with TestClient(app) as client:
        approved = client.post(f"/profile-versions/{version_id}/decision", json={"decision": "approve", "decision_maker": "Agency Owner"})
    with SessionLocal() as database:
        completed = process_onboarding_run(database, run_id)
        completed_status = completed.status
        tasks = list(database.scalars(select(models.Task).where(models.Task.client_id == client_id)))
        saved_client = database.get(models.Client, client_id)
        client_status = saved_client.status

    assert approved.status_code == 200
    assert completed_status == "completed"
    assert client_status == "ready_for_fulfillment"
    assert {task.title for task in tasks} == {
        "Begin seo fulfillment for Handoff Automation",
        "Begin reporting fulfillment for Handoff Automation",
    }
    assert all(task.status == "proposed" for task in tasks)


def test_temporary_openai_failure_retries_three_times_then_blocks(monkeypatch) -> None:
    from app.openai_service import OpenAIInterpretationError

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(
        "app.onboarding_automation.openai_service.interpret",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OpenAIInterpretationError("openai_temporarily_unavailable", retryable=True)
        ),
    )
    with TestClient(app) as client:
        _client_id, _intake_id, run_id = create_client_and_intake(
            client, "Retry Automation", "retry-auto.com"
        )
    statuses = []
    with SessionLocal() as database:
        for _attempt in range(3):
            run = process_onboarding_run(database, run_id)
            statuses.append((run.status, run.attempt_count, run.last_error))

    assert statuses == [
        ("queued", 1, "openai_temporarily_unavailable"),
        ("queued", 2, "openai_temporarily_unavailable"),
        ("blocked", 3, "openai_temporarily_unavailable"),
    ]


def test_missing_interpretation_information_prevents_profile_approval(monkeypatch) -> None:
    patch_happy_providers(monkeypatch, "missing-auto.com")
    monkeypatch.setattr(
        "app.onboarding_automation.openai_service.interpret",
        lambda intake, business_name, role: (
            {"business_name": business_name, "domain": intake.domain},
            ["verified service list"],
            [],
            "awaiting_information",
        ),
    )
    with TestClient(app) as client:
        client_id, _intake_id, run_id = create_client_and_intake(
            client, "Missing Information Automation", "missing-auto.com"
        )
    with SessionLocal() as database:
        process_onboarding_run(database, run_id)
        version_id = database.scalar(
            select(models.ProfileVersion.id).where(models.ProfileVersion.client_id == client_id)
        )
    with TestClient(app) as client:
        response = client.post(
            f"/profile-versions/{version_id}/decision",
            json={"decision": "approve", "decision_maker": "Agency Owner"},
        )

    assert response.status_code == 409
    assert "Resolve missing and conflicting information" in response.json()["detail"]


def test_new_intake_requires_new_approval_and_advances_official_profile(monkeypatch) -> None:
    patch_happy_providers(monkeypatch, "versioned-auto.com")
    with TestClient(app) as client:
        client_id, first_intake_id, first_run_id = create_client_and_intake(
            client, "Versioned Automation", "versioned-auto.com"
        )
    with SessionLocal() as database:
        process_onboarding_run(database, first_run_id)
        first_version_id = database.scalar(
            select(models.ProfileVersion.id).where(models.ProfileVersion.intake_id == first_intake_id)
        )
    with TestClient(app) as client:
        assert client.post(
            f"/profile-versions/{first_version_id}/decision",
            json={"decision": "approve", "decision_maker": "Agency Owner"},
        ).status_code == 200
    with SessionLocal() as database:
        process_onboarding_run(database, first_run_id)

    payload = make_intake_payload()
    payload["domain"] = "versioned-auto.com"
    payload["business_hours"] = "Monday-Saturday 8am-6pm"
    with TestClient(app) as client:
        second_intake = client.post(f"/clients/{client_id}/intakes", json=payload).json()
        second_run_id = client.get(f"/clients/{client_id}/onboarding-automation").json()["id"]
    with SessionLocal() as database:
        second_run = process_onboarding_run(database, second_run_id)
        second_status = second_run.status
        second_version_id = database.scalar(
            select(models.ProfileVersion.id).where(models.ProfileVersion.intake_id == second_intake["id"])
        )
        official_before = database.scalar(
            select(models.OfficialProfile).where(models.OfficialProfile.client_id == client_id)
        )
        official_before_id = official_before.approved_version_id

    assert second_status == "awaiting_profile_approval"
    assert official_before_id == first_version_id
    with TestClient(app) as client:
        assert client.post(
            f"/profile-versions/{second_version_id}/decision",
            json={"decision": "approve", "decision_maker": "Agency Owner"},
        ).status_code == 200
    with SessionLocal() as database:
        official_after = database.scalar(
            select(models.OfficialProfile).where(models.OfficialProfile.client_id == client_id)
        )
        approved_versions = list(
            database.scalars(
                select(models.ProfileVersion).where(
                    models.ProfileVersion.client_id == client_id,
                    models.ProfileVersion.status == "approved",
                )
            )
        )

    assert official_after.approved_version_id == second_version_id
    assert {item.id for item in approved_versions} == {first_version_id, second_version_id}
