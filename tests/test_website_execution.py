"""Approved website execution commits only packet-scoped, non-secret files."""

from fastapi.testclient import TestClient

from app.main import app
from app.routes import website_execution
from app.client_provider_verification import ProviderVerificationBlocked
from tests.test_codex_work_packets import link_repository, link_website, packet_request, approved_task


def test_website_execution_commits_scoped_files_and_is_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(website_execution, "require_provider_health", lambda *args, **kwargs: {})
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Website Execute")
        connection = link_website(client, client_id, "website-execute")
        link_repository(client, client_id, "website-execute")
        packet = client.post(
            f"/tasks/{task_id}/codex-work-packet",
            json=packet_request(connection, "website-execute"),
        ).json()
        monkeypatch.setattr(
            website_execution,
            "commit_website_files",
            lambda **_kwargs: {"branch": "main", "changed_paths": ["app/page.tsx"], "commit_shas": ["abc123"]},
        )
        payload = {
            "operation_key": "website-execution-1",
            "packet_id": packet["id"],
            "commit_message": "Apply approved website change",
            "files": [{"path": "app/page.tsx", "content": "export default function Page() { return null }"}],
        }
        first = client.post(f"/tasks/{task_id}/website-executions", json=payload)
        repeated = client.post(f"/tasks/{task_id}/website-executions", json=payload)

    assert first.status_code == 201, first.text
    assert first.json()["evidence"]["executor"] == "github_app"
    assert first.json()["evidence"]["deployment"]["status"] == "pending_linked_vercel_deployment"
    assert repeated.json()["id"] == first.json()["id"]
    assert repeated.json()["reused_existing"] is True


def test_website_file_validation_rejects_scope_escape_and_secrets() -> None:
    from app.website_execution import WebsiteExecutionError, validate_files

    for content, expected in [
        ("safe", "website_file_path_outside_packet"),
        ("-----BEGIN PRIVATE KEY-----", "website_file_secret_detected"),
    ]:
        try:
            validate_files(
                [{"path": "app/page.tsx", "content": content}],
                    ["public/**"] if content == "safe" else ["app/**"],
                [".env*", "**/.env*"],
            )
        except WebsiteExecutionError as error:
            assert str(error) == expected
        else:
            raise AssertionError("unsafe website file was accepted")


def test_website_execution_fails_closed_when_live_provider_gate_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        website_execution,
        "require_provider_health",
        lambda *args, **kwargs: (_ for _ in ()).throw(ProviderVerificationBlocked(["github_authorization_failed"])),
    )
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Website Provider Gate")
        connection = link_website(client, client_id, "website-provider-gate")
        link_repository(client, client_id, "website-provider-gate")
        packet = client.post(f"/tasks/{task_id}/codex-work-packet", json=packet_request(connection, "website-provider-gate")).json()
        response = client.post(
            f"/tasks/{task_id}/website-executions",
            json={
                "operation_key": "website-provider-gate",
                "packet_id": packet["id"],
                "commit_message": "Apply approved website change",
                "files": [{"path": "app/page.tsx", "content": "safe"}],
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "provider_verification_required",
        "providers": ["github_authorization_failed"],
    }


def test_website_execution_can_poll_ready_vercel_deployment(monkeypatch) -> None:
    monkeypatch.setattr(website_execution, "require_provider_health", lambda *args, **kwargs: {})
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Website Deployment Poll")
        connection = link_website(client, client_id, "website-deployment-poll")
        link_repository(client, client_id, "website-deployment-poll")
        packet = client.post(
            f"/tasks/{task_id}/codex-work-packet",
            json=packet_request(connection, "website-deployment-poll"),
        ).json()
        monkeypatch.setattr(
            website_execution,
            "commit_website_files",
            lambda **_kwargs: {"branch": "main", "changed_paths": ["app/page.tsx"], "commit_shas": ["abc123"]},
        )
        monkeypatch.setenv("MAX_ENABLE_EXTERNAL_WRITES", "true")
        monkeypatch.setenv("VERCEL_API_TOKEN", "test-token")
        monkeypatch.setattr(
            website_execution.VercelAdapter,
            "trigger_git_deployment",
            lambda *_args, **_kwargs: {"deployment_id": "dpl_123", "url": "client.example.com", "ready_state": "queued"},
        )
        created = client.post(
            f"/tasks/{task_id}/website-executions",
            json={
                "operation_key": "website-deployment-poll",
                "packet_id": packet["id"],
                "commit_message": "Apply approved website change",
                "files": [{"path": "app/page.tsx", "content": "safe"}],
            },
        ).json()
        monkeypatch.setattr(
            website_execution.VercelAdapter,
            "get_deployment",
            lambda *_args, **_kwargs: {"deployment_id": "dpl_123", "ready_state": "ready", "url": "client.example.com", "error_code": None, "error_message": None},
        )
        polled = client.post(f"/website-executions/{created['id']}/deployment-poll")

    assert created["evidence"]["deployment"]["status"] == "queued"
    assert polled.status_code == 200
    assert polled.json()["evidence"]["deployment"]["status"] == "ready"
    assert polled.json()["evidence"]["deployment"]["deployment_verified"] is True


def test_website_execution_can_be_rolled_back_once_and_requires_reverification(monkeypatch) -> None:
    monkeypatch.setattr(website_execution, "require_provider_health", lambda *args, **kwargs: {})
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Website Rollback")
        connection = link_website(client, client_id, "website-rollback")
        link_repository(client, client_id, "website-rollback")
        packet = client.post(
            f"/tasks/{task_id}/codex-work-packet",
            json=packet_request(connection, "website-rollback"),
        ).json()
        monkeypatch.setattr(
            website_execution,
            "commit_website_files",
            lambda **_kwargs: {"branch": "main", "changed_paths": ["app/page.tsx"], "commit_shas": ["abc123"]},
        )
        created = client.post(
            f"/tasks/{task_id}/website-executions",
            json={
                "operation_key": "website-rollback-execution",
                "packet_id": packet["id"],
                "commit_message": "Apply approved website change",
                "files": [{"path": "app/page.tsx", "content": "safe"}],
            },
        ).json()
        monkeypatch.setattr(
            website_execution,
            "revert_website_commit",
            lambda **_kwargs: {
                "reverted_commit_sha": "abc123",
                "rollback_commit_sha": "rollback456",
                "branch": "main",
            },
        )
        rolled_back = client.post(
            f"/website-executions/{created['id']}/rollback",
            json={"operation_key": "website-rollback-1", "reason": "Restore the prior approved state."},
        )
        repeated = client.post(
            f"/website-executions/{created['id']}/rollback",
            json={"operation_key": "website-rollback-1", "reason": "Restore the prior approved state."},
        )

    assert rolled_back.status_code == 200
    assert rolled_back.json()["evidence"]["rollback"]["status"] == "completed"
    assert rolled_back.json()["evidence"]["rollback"]["rollback_commit_sha"] == "rollback456"
    assert repeated.status_code == 200
    assert repeated.json()["reused_existing"] is True
