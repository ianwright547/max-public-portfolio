import json

from app.github_service import GitHubRepository
from app.google_business_profile_service import BusinessProfileInspection
from app.vercel_service import VercelProject
from scripts import check_provider_connections


def _configure(monkeypatch):
    values = {
        "GITHUB_OWNER": "agency",
        "GITHUB_REPOSITORY": "max-client",
        "GITHUB_APP_ID": "app-1",
        "GITHUB_APP_PRIVATE_KEY": "private-key",
        "GITHUB_APP_INSTALLATION_ID": "installation-1",
        "VERCEL_PROJECT_ID": "prj_123",
        "VERCEL_API_TOKEN": "vercel-token",
        "GOOGLE_CLIENT_ID": "google-client",
        "GOOGLE_CLIENT_SECRET": "google-secret",
        "GOOGLE_REFRESH_TOKEN": "google-refresh",
        "GBP_ACCOUNT_ID": "accounts/1",
        "GBP_LOCATION_ID": "locations/2",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_provider_probe_verifies_target_mappings_without_secrets(monkeypatch, capsys):
    _configure(monkeypatch)
    monkeypatch.setattr(
        check_provider_connections.GitHubAppAdapter,
        "get_repository",
        lambda self, owner, repository: GitHubRepository("1", owner, repository, "https://github.com/agency/max-client", "main", True),
    )
    monkeypatch.setattr(
        check_provider_connections.VercelAdapter,
        "get_project",
        lambda self, project: VercelProject(project, "Max Client", "https://max.example.com", "available"),
    )
    monkeypatch.setattr(
        check_provider_connections.GoogleBusinessProfileAdapter,
        "inspect_location",
        lambda self, account, location: BusinessProfileInspection(location, "Max Client", None, None, (), False, False, None, 3, 4.5),
    )
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "private-secret")

    assert check_provider_connections.main() == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["status"] == "verified"
    assert payload["github"]["repository"] == "max-client"
    assert "private-secret" not in output


def test_provider_probe_rejects_repository_mismatch(monkeypatch, capsys):
    _configure(monkeypatch)
    monkeypatch.setattr(
        check_provider_connections.GitHubAppAdapter,
        "get_repository",
        lambda self, owner, repository: GitHubRepository("1", "other", repository, "https://github.com/other/max-client", "main", True),
    )
    assert check_provider_connections.main() == 1
    assert capsys.readouterr().err.strip() == "Provider verification failed: github_repository_mismatch"


def test_provider_probe_suppresses_provider_error_details(monkeypatch, capsys):
    _configure(monkeypatch)

    def fail(self, owner, repository):
        from app.github_service import GitHubIntegrationError

        raise GitHubIntegrationError("github_authorization_failed")

    monkeypatch.setattr(check_provider_connections.GitHubAppAdapter, "get_repository", fail)
    assert check_provider_connections.main() == 1
    assert capsys.readouterr().err.strip() == "Provider verification failed: github_authorization_failed"


def test_provider_probe_requires_vercel_production_domain(monkeypatch, capsys):
    _configure(monkeypatch)
    monkeypatch.setattr(
        check_provider_connections.GitHubAppAdapter,
        "get_repository",
        lambda self, owner, repository: GitHubRepository("1", owner, repository, "https://github.com/agency/max-client", "main", True),
    )
    monkeypatch.setattr(
        check_provider_connections.VercelAdapter,
        "get_project",
        lambda self, project: VercelProject(project, "Max Client", None, "available"),
    )
    assert check_provider_connections.main() == 1
    assert capsys.readouterr().err.strip() == "Provider verification failed: vercel_production_domain_missing"
