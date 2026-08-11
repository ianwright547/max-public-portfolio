"""Website generation uses versioned prompt context before execution."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.routes import website_generation, website_execution
from tests.test_codex_work_packets import approved_task, link_repository, link_website, packet_request


def test_generated_files_are_sent_through_existing_execution_gate(monkeypatch) -> None:
    monkeypatch.setattr(website_execution, "require_provider_health", lambda *args, **kwargs: {})
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Website Generate")
        connection = link_website(client, client_id, "website-generate")
        link_repository(client, client_id, "website-generate")
        packet = client.post(
            f"/tasks/{task_id}/codex-work-packet", json=packet_request(connection, "website-generate")
        ).json()
        monkeypatch.setattr(
            website_generation,
            "generate_files",
            lambda *_args, **_kwargs: ([{"path": "app/page.tsx", "content": "export default function Page() {}"}], "prompt-artifact-1"),
        )
        monkeypatch.setattr(
            website_execution,
            "commit_website_files",
            lambda **_kwargs: {"branch": "main", "changed_paths": ["app/page.tsx"], "commit_shas": ["sha-1"]},
        )
        response = client.post(
            f"/tasks/{task_id}/website-generation",
            json={"operation_key": "website-generation-1", "packet_id": packet["id"], "commit_message": "Generate approved site"},
        )

    assert response.status_code == 201, response.text
    assert response.json()["evidence"]["executor"] == "github_app"
    audit = response.json()["evidence"]["website_artifact_audit"]
    assert audit["checks"]["files_validated"] is True
    assert audit["checks"]["page_inventory_present"] is False


def test_website_generation_preview_is_persisted_without_external_commit(monkeypatch) -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Website Preview")
        connection = link_website(client, client_id, "website-preview")
        link_repository(client, client_id, "website-preview")
        packet = client.post(
            f"/tasks/{task_id}/codex-work-packet", json=packet_request(connection, "website-preview")
        ).json()
        monkeypatch.setattr(
            website_generation,
            "generate_files",
            lambda *_args, **_kwargs: ([{"path": "app/page.tsx", "content": "safe preview"}], "prompt-artifact-2"),
        )
        monkeypatch.setattr(
            website_generation,
            "validate_files",
            lambda files, allowed_paths, prohibited_paths: None,
        )
        preview = client.post(
            f"/tasks/{task_id}/website-generation-preview",
            json={"operation_key": "website-preview-1", "packet_id": packet["id"], "model_role": "balanced"},
        )
        repeated = client.post(
            f"/tasks/{task_id}/website-generation-preview",
            json={"operation_key": "website-preview-1", "packet_id": packet["id"], "model_role": "balanced"},
        )
        fetched = client.get(f"/website-previews/{preview.json()['id']}")

    assert preview.status_code == 201, preview.text
    assert preview.json()["status"] == "draft"
    assert preview.json()["file_manifest"][0]["path"] == "app/page.tsx"
    assert preview.json()["file_manifest"][0]["sha256"]
    assert preview.json()["technical_audit"]["checks"]["files_validated"] is True
    assert preview.json()["technical_audit"]["checks"]["page_inventory_present"] is False
    assert preview.json()["technical_audit"]["checks"]["sitemap_present"] is True
    assert preview.json()["technical_audit"]["checks"]["robots_present"] is True
    assert any(item["path"] == "public/sitemap.xml" for item in preview.json()["files"])
    assert repeated.status_code == 201
    assert repeated.json()["id"] == preview.json()["id"]
    assert fetched.status_code == 200


def test_website_preview_reports_file_level_comparison(monkeypatch) -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Website Preview Comparison")
        connection = link_website(client, client_id, "website-preview-comparison")
        link_repository(client, client_id, "website-preview-comparison")
        packet = client.post(
            f"/tasks/{task_id}/codex-work-packet", json=packet_request(connection, "website-preview-comparison")
        ).json()
        calls = {"count": 0}

        def generated(*_args, **_kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return ([
                    {"path": "app/page.tsx", "content": "same"},
                    {"path": "app/old.tsx", "content": "remove"},
                ], "prompt-artifact-3")
            return ([
                {"path": "app/page.tsx", "content": "changed"},
                {"path": "app/new.tsx", "content": "add"},
            ], "prompt-artifact-4")

        monkeypatch.setattr(website_generation, "generate_files", generated)
        first = client.post(
            f"/tasks/{task_id}/website-generation-preview",
            json={"operation_key": "website-preview-compare-1", "packet_id": packet["id"]},
        ).json()
        second = client.post(
            f"/tasks/{task_id}/website-generation-preview",
            json={"operation_key": "website-preview-compare-2", "packet_id": packet["id"]},
        ).json()

    assert first["comparison"]["baseline_preview_id"] is None
    assert second["comparison"]["baseline_preview_id"] == first["id"]
    assert second["comparison"]["added_paths"] == ["app/new.tsx"]
    assert second["comparison"]["removed_paths"] == ["app/old.tsx"]
    assert second["comparison"]["changed_paths"] == ["app/page.tsx"]
    assert second["comparison"]["unchanged_paths"] == ["public/robots.txt", "public/sitemap.xml"]


def test_generated_html_audit_reports_inventory_sitemap_and_metadata_checks() -> None:
    from app.website_execution import audit_generated_website_files

    audit = audit_generated_website_files(
        [
            {
                "path": "public/index.html",
                "content": '<html><head><title>Auto Repair</title></head><body><h1>Auto Repair</h1></body></html>',
            },
            {"path": "public/robots.txt", "content": "User-agent: *\nAllow: /\n"},
            {"path": "public/sitemap.xml", "content": "<urlset/>"},
        ]
    )

    assert audit["page_inventory"] == ["public/index.html"]
    assert audit["checks"]["html_pages_have_one_title"] is True
    assert audit["checks"]["html_pages_have_one_h1"] is True
    assert audit["checks"]["sitemap_present"] is True
    assert audit["checks"]["robots_present"] is True
    assert audit["failed"] == 0


def test_site_artifacts_are_generated_from_approved_routes_and_domain() -> None:
    from app.website_execution import ensure_site_artifacts

    files = ensure_site_artifacts(
        [{"path": "app/page.tsx", "content": "export default function Page() {}"}],
        "https://repair.example.com",
    )
    by_path = {item["path"]: item["content"] for item in files}

    assert "public/sitemap.xml" in by_path
    assert "https://repair.example.com/" in by_path["public/sitemap.xml"]
    assert "public/robots.txt" in by_path
    assert "Sitemap: https://repair.example.com/sitemap.xml" in by_path["public/robots.txt"]


def test_direct_openai_website_generation_is_budget_gated(monkeypatch) -> None:
    from app import models
    from app.database import SessionLocal
    from app.website_generation_service import WebsiteGenerationError, generate_files

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MONTHLY_AI_BUDGET_USD", "0.01")
    network_calls = {"count": 0}

    def fail_network(*_args, **_kwargs):
        network_calls["count"] += 1
        raise AssertionError("budget gate must run before OpenAI")

    monkeypatch.setattr("app.website_generation_service.urlopen", fail_network)
    with TestClient(app) as client:
        _client_id, task_id = approved_task(client, "Budgeted Website Generate")
    with SessionLocal() as database:
        task = database.get(models.Task, task_id)
        try:
            generate_files(database, task)
        except WebsiteGenerationError as error:
            assert error.code == "monthly_ai_budget_exceeded"
        else:
            raise AssertionError("website generation should stop at the AI budget gate")

    assert network_calls["count"] == 0


def test_website_generation_usage_survives_invalid_provider_output(monkeypatch) -> None:
    """A paid provider response is charged even when its payload is unusable."""
    import json

    from app import models
    from app.database import SessionLocal
    from app.website_generation_service import WebsiteGenerationError, generate_files

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MONTHLY_AI_BUDGET_USD", "100000")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "output_text": "not valid JSON",
                }
            ).encode()

    monkeypatch.setattr("app.website_generation_service.urlopen", lambda *_args, **_kwargs: Response())
    class Artifact:
        id = "prompt-artifact-invalid-output"
        system_prompt = "system"
        user_prompt = "user"

    monkeypatch.setattr(
        "app.website_generation_service.compile_prompt",
        lambda *_args, **_kwargs: (Artifact(), False),
    )
    with TestClient(app) as client:
        _client_id, task_id = approved_task(client, "Charged Invalid Website Output")
    with SessionLocal() as database:
        task = database.get(models.Task, task_id)
        try:
            generate_files(database, task)
        except WebsiteGenerationError as error:
            assert error.code == "website_generation_invalid_json"
        else:
            raise AssertionError("invalid provider JSON should fail generation")
        usage = database.scalar(
            select(models.AIUsageRecord).where(
                models.AIUsageRecord.operation_key == f"website-generation:{task_id}"
            )
        )

    assert usage is not None


def test_direct_website_generation_is_blocked_without_paid_entitlement(monkeypatch) -> None:
    monkeypatch.setenv("MAX_BILLING_ENFORCEMENT", "true")
    with TestClient(app) as client:
        _client_id, task_id = approved_task(client, "Paid Website Generate")
        monkeypatch.setattr(
            website_generation,
            "generate_files",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("generation must be gated")),
        )
        response = client.post(
            f"/tasks/{task_id}/website-generation",
            json={
                "operation_key": "paid-website-generation",
                "packet_id": "missing-packet",
                "commit_message": "Generate approved site",
            },
        )

    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "billing_subscription_required"


def test_direct_website_generation_validates_packet_before_ai(monkeypatch) -> None:
    with TestClient(app) as client:
        _client_id, task_id = approved_task(client, "Packet Before Website Generate")
        monkeypatch.setattr(
            website_generation,
            "generate_files",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("generation must follow packet validation")),
        )
        response = client.post(
            f"/tasks/{task_id}/website-generation",
            json={
                "operation_key": "packet-before-website-generation",
                "packet_id": "missing-packet",
                "commit_message": "Generate approved site",
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Work packet does not match this client task"
