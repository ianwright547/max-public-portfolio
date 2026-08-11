"""Read-only GitHub App verification tests with no live GitHub dependency."""

import pytest

from app.github_service import GitHubAppAdapter, GitHubIntegrationError


class Response:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        return self._body


def test_missing_github_app_configuration_is_explicit() -> None:
    with pytest.raises(GitHubIntegrationError, match="github_app_configuration_missing"):
        GitHubAppAdapter("", "", "")


def test_repository_metadata_is_normalized_without_writing(monkeypatch) -> None:
    adapter = GitHubAppAdapter("123", "private-key", "456")
    monkeypatch.setattr(adapter, "_installation_token", lambda: "installation-token")
    requests = []

    def fake_get(url, headers, timeout):
        requests.append((url, headers, timeout))
        return Response(
            200,
            {
                "id": 42,
                "name": "client-site",
                "html_url": "https://github.com/agency/client-site",
                "default_branch": "main",
                "private": True,
                "owner": {"login": "agency"},
            },
        )

    monkeypatch.setattr("app.github_service.httpx.get", fake_get)
    repository = adapter.get_repository("agency", "client-site")

    assert repository.repository_id == "42"
    assert repository.owner == "agency"
    assert repository.default_branch == "main"
    assert repository.private is True
    assert requests[0][0].endswith("/repos/agency/client-site")
    assert requests[0][1]["Authorization"] == "Bearer installation-token"


def test_github_errors_are_safe_and_retryable_when_appropriate(monkeypatch) -> None:
    adapter = GitHubAppAdapter("123", "private-key", "456")
    monkeypatch.setattr(adapter, "_installation_token", lambda: "installation-token")
    monkeypatch.setattr(
        "app.github_service.httpx.get", lambda *args, **kwargs: Response(429, {})
    )

    with pytest.raises(GitHubIntegrationError) as error:
        adapter.get_repository("agency", "client-site")

    assert error.value.code == "github_temporarily_unavailable"
    assert error.value.retryable is True


def test_invalid_private_key_returns_a_safe_error() -> None:
    adapter = GitHubAppAdapter("123", "not-a-private-key", "456")

    with pytest.raises(GitHubIntegrationError) as error:
        adapter._app_jwt()

    assert error.value.code == "github_private_key_invalid"
    assert error.value.retryable is False


def test_list_installation_repositories_discovers_accessible_repos(monkeypatch) -> None:
    adapter = GitHubAppAdapter("123", "private-key", "456")
    monkeypatch.setattr(adapter, "_installation_token", lambda: "installation-token")

    def fake_get(url, params, headers, timeout):
        assert url.endswith("/installation/repositories")
        assert params == {"per_page": 100, "page": 1}
        return Response(
            200,
            {
                "repositories": [
                    {
                        "id": 88,
                        "name": "discovered-site",
                        "html_url": "https://github.com/agency/discovered-site",
                        "default_branch": "main",
                        "private": True,
                        "owner": {"login": "agency"},
                    }
                ]
            },
        )

    monkeypatch.setattr("app.github_service.httpx.get", fake_get)
    repository = adapter.list_repositories()[0]

    assert repository.repository_id == "88"
    assert repository.html_url == "https://github.com/agency/discovered-site"


def test_commit_files_writes_only_supplied_content(monkeypatch) -> None:
    adapter = GitHubAppAdapter("123", "private-key", "456")
    monkeypatch.setattr(adapter, "_installation_token", lambda: "installation-token")
    requests = []

    def fake_get(url, headers, timeout, **kwargs):
        if "/git/ref/heads/" in url:
            return Response(200, {"object": {"sha": "base-sha"}})
        return Response(404, {})

    def fake_put(url, headers, json, timeout):
        requests.append((url, json))
        return Response(200, {"commit": {"sha": "commit-sha"}})

    monkeypatch.setattr("app.github_service.httpx.get", fake_get)
    monkeypatch.setattr("app.github_service.httpx.put", fake_put)
    result = adapter.commit_files(
        "agency", "client-site", "main", [{"path": "app/page.tsx", "content": "safe"}], "Approved change"
    )

    assert result == {"branch": "main", "changed_paths": ["app/page.tsx"], "commit_shas": ["commit-sha"]}
    assert requests[0][1]["branch"] == "main"
    assert requests[0][1]["message"] == "Approved change"
