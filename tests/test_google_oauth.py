"""Google OAuth setup tests use a mocked token exchange and never call Google."""

from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.database import SessionLocal
from app.main import app
from app.routes import google_oauth


def google_config(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id-for-test")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-for-test")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://testserver/google/oauth/callback")


def test_start_redirects_with_offline_access_and_required_scopes(monkeypatch) -> None:
    google_config(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/google/oauth/start", follow_redirects=False)

    assert response.status_code == 307
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert set(query["scope"][0].split()) == set(google_oauth.GOOGLE_SCOPES)
    assert query["state"][0]


def test_start_requires_google_configuration(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_REDIRECT_URI", raising=False)
    with TestClient(app) as client:
        response = client.get("/google/oauth/start")

    assert response.status_code == 503
    assert response.json() == {"detail": "google_oauth_not_configured"}


def test_callback_shows_refresh_token_once_and_marks_state_used(monkeypatch) -> None:
    google_config(monkeypatch)
    with TestClient(app) as client:
        start = client.get("/google/oauth/start", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

        monkeypatch.setattr(
            google_oauth,
            "_exchange_code_for_tokens",
            lambda *args: {"refresh_token": "refresh-token-test", "access_token": "never-saved"},
        )
        callback = client.get(f"/google/oauth/callback?code=code-for-test&state={state}")

    assert callback.status_code == 200
    assert "refresh-token-test" in callback.text
    with SessionLocal() as database:
        saved_state = database.scalar(
            select(models.GoogleOAuthState).where(
                models.GoogleOAuthState.state_hash == google_oauth._state_digest(state)
            )
        )
        assert saved_state is not None
        assert saved_state.used_at is not None
        # The credential is intentionally not persisted by this setup flow.
        assert not hasattr(saved_state, "refresh_token")


def test_callback_rejects_replay(monkeypatch) -> None:
    google_config(monkeypatch)
    with TestClient(app) as client:
        start = client.get("/google/oauth/start", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        monkeypatch.setattr(google_oauth, "_exchange_code_for_tokens", lambda *args: {"refresh_token": "token"})
        assert client.get(f"/google/oauth/callback?code=code&state={state}").status_code == 200
        replay = client.get(f"/google/oauth/callback?code=code&state={state}")

    assert replay.status_code == 400
    assert replay.json() == {"detail": "google_oauth_state_invalid_or_expired"}


def test_callback_rejects_expired_state(monkeypatch) -> None:
    google_config(monkeypatch)
    with TestClient(app) as client:
        start = client.get("/google/oauth/start", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    with SessionLocal() as database:
        saved_state = database.scalar(
            select(models.GoogleOAuthState).where(
                models.GoogleOAuthState.state_hash == google_oauth._state_digest(state)
            )
        )
        assert saved_state is not None
        saved_state.expires_at = datetime.utcnow() - timedelta(seconds=1)
        database.commit()
    with TestClient(app) as client:
        response = client.get(f"/google/oauth/callback?code=code&state={state}")
    assert response.status_code == 400


def test_callback_requires_refresh_token(monkeypatch) -> None:
    google_config(monkeypatch)
    with TestClient(app) as client:
        start = client.get("/google/oauth/start", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        monkeypatch.setattr(google_oauth, "_exchange_code_for_tokens", lambda *args: {"access_token": "only"})
        response = client.get(f"/google/oauth/callback?code=code&state={state}")

    assert response.status_code == 502
    assert response.json() == {"detail": "google_refresh_token_missing_restart_with_consent"}


def test_token_exchange_uses_http_post_without_logging_credentials(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"refresh_token":"returned-token"}'

    def fake_urlopen(request, timeout):
        captured["method"] = request.method
        captured["body"] = request.data
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(google_oauth, "urlopen", fake_urlopen)
    result = google_oauth._exchange_code_for_tokens("code", "client", "secret", "https://callback.test")

    assert result == {"refresh_token": "returned-token"}
    assert captured["method"] == "POST"
    assert captured["timeout"] == 15
    assert b"grant_type=authorization_code" in captured["body"]
