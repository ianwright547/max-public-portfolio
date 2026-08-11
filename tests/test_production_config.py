from scripts.check_production_config import main


def _set_core(monkeypatch):
    values = {
        "MAX_DATABASE_URL": "postgresql://user:password@example.test/max",
        "AUTH_SECRET": "a-secret",
        "MAX_ALLOWED_GOOGLE_EMAILS": "owner@example.com",
        "GOOGLE_CLIENT_ID": "client-id",
        "GOOGLE_CLIENT_SECRET": "client-secret",
        "GOOGLE_REDIRECT_URI": "https://max.example.com/auth/google/callback",
        "JOB_RUNNER_SECRET": "job-secret",
        "CRON_SECRET": "cron-secret",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_core_config_passes(monkeypatch):
    _set_core(monkeypatch)
    assert main([]) == 0


def test_core_config_rejects_sqlite(monkeypatch):
    _set_core(monkeypatch)
    monkeypatch.setenv("MAX_DATABASE_URL", "sqlite:///./max.db")
    assert main([]) == 1


def test_full_config_requires_provider_connections(monkeypatch):
    _set_core(monkeypatch)
    assert main(["--profile", "full"]) == 1


def test_full_config_rejects_non_https_public_report_origin(monkeypatch):
    _set_core(monkeypatch)
    full_values = {
        "SLACK_BOT_TOKEN": "token",
        "SLACK_SIGNING_SECRET": "signing-secret",
        "SLACK_WORKSPACE_ID": "T_MAX",
        "SLACK_OWNER_USER_IDS": "U_OWNER",
        "MAX_PUBLIC_BASE_URL": "http://max.example.test/path",
        "OPENAI_API_KEY": "openai-key",
        "GITHUB_APP_ID": "app-id",
        "GITHUB_APP_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----\\nprivate-key\\n-----END PRIVATE KEY-----",
        "GITHUB_APP_INSTALLATION_ID": "installation-id",
        "GITHUB_OWNER": "owner",
        "GITHUB_REPOSITORY": "repo",
        "VERCEL_API_TOKEN": "vercel-token",
        "VERCEL_PROJECT_ID": "project-id",
        "GOOGLE_REFRESH_TOKEN": "refresh-token",
        "GBP_ACCOUNT_ID": "account-id",
        "GBP_LOCATION_ID": "location-id",
        "MAX_FULFILLMENT_MODE": "codex_handoff",
    }
    for name, value in full_values.items():
        monkeypatch.setenv(name, value)

    assert main(["--profile", "full"]) == 1
    monkeypatch.setenv("MAX_PUBLIC_BASE_URL", "https://max.example.test")
    assert main(["--profile", "full"]) == 0


def test_core_config_rejects_non_https_google_callback(monkeypatch):
    _set_core(monkeypatch)
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://max.example.com/auth/google/callback")
    assert main([]) == 1
