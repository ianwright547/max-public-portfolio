"""Tests for read-only Vercel project verification."""

import json

import pytest

from app.vercel_service import VercelAdapter, VercelIntegrationError


def test_missing_vercel_token_is_explicit() -> None:
    with pytest.raises(VercelIntegrationError, match="vercel_token_missing"):
        VercelAdapter("")


def test_project_response_is_normalized_without_deploying(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "id": "prj_test",
                    "name": "test-project",
                    "targets": {"production": {"url": "test.example.com"}},
                }
            ).encode()

    monkeypatch.setattr("app.vercel_service.urlopen", lambda request, timeout: Response())
    project = VercelAdapter("test-token").get_project("prj_test")

    assert project.project_id == "prj_test"
    assert project.project_name == "test-project"
    assert project.production_url == "test.example.com"


def test_unauthorized_response_is_not_retryable(monkeypatch) -> None:
    from urllib.error import HTTPError

    def fail(request, timeout):
        raise HTTPError(request.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr("app.vercel_service.urlopen", fail)
    with pytest.raises(VercelIntegrationError) as error:
        VercelAdapter("test-token").get_project("prj_test")
    assert error.value.code == "vercel_authorization_failed"
    assert error.value.retryable is False


def test_list_projects_discovers_domains_and_github_link(monkeypatch) -> None:
    class ListResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "projects": [
                        {
                            "id": "prj_discovered",
                            "name": "client-site",
                            "targets": {"production": {"url": "client-site.vercel.app"}},
                            "latestDeployments": [{"alias": ["client.example.com"]}],
                            "link": {"type": "github", "org": "agency", "repo": "client-site"},
                        }
                    ],
                    "pagination": {"next": None},
                }
            ).encode()

    monkeypatch.setattr("app.vercel_service.urlopen", lambda request, timeout: ListResponse())
    project = VercelAdapter("test-token").list_projects()[0]

    assert project.project_id == "prj_discovered"
    assert project.production_domains == ("client-site.vercel.app", "client.example.com")
    assert project.repository_url == "https://github.com/agency/client-site"


def test_trigger_git_deployment_records_provider_reference(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"id":"dpl_123","url":"client-site.vercel.app","readyState":"QUEUED"}'

    captured = {}

    def fake_urlopen(request, timeout):
        captured["method"] = request.method
        captured["body"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setattr("app.vercel_service.urlopen", fake_urlopen)
    result = VercelAdapter("test-token").trigger_git_deployment(
        "prj_test", "agency", "client-site", "main"
    )

    assert captured["method"] == "POST"
    assert captured["body"]["gitSource"]["ref"] == "main"
    assert result["deployment_id"] == "dpl_123"


def test_get_deployment_normalizes_ready_state(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return b'{"id":"dpl_123","readyState":"READY","url":"client.example.com"}'

    monkeypatch.setattr("app.vercel_service.urlopen", lambda _request, timeout: FakeResponse())
    result = VercelAdapter("test-token").get_deployment("dpl_123")

    assert result == {
        "deployment_id": "dpl_123",
        "ready_state": "ready",
        "url": "client.example.com",
        "error_code": None,
        "error_message": None,
    }
