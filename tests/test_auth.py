"""Owner authentication fails closed and protects browser mutations."""

from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app import models
from app.auth_service import SESSION_COOKIE, create_owner_session, digest
from app.database import SessionLocal
from app.main import app
from app.routes import google_oauth


OWNER_EMAIL = "owner@example.com"


def configure_auth(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret-with-enough-entropy")
    monkeypatch.setenv("MAX_ALLOWED_GOOGLE_EMAILS", OWNER_EMAIL)
    monkeypatch.setenv("MAX_REQUIRE_AUTH", "true")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "owner-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "owner-client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://testserver/google/oauth/callback")


def owner_cookie() -> str:
    with SessionLocal() as database:
        _session, token = create_owner_session(database, OWNER_EMAIL)
    return token


def test_health_and_callback_are_public_but_data_routes_require_login(monkeypatch) -> None:
    configure_auth(monkeypatch)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        api = client.get("/clients")
        page = client.get("/dashboard", headers={"Accept": "text/html"}, follow_redirects=False)

        assert api.status_code == 401
        assert page.status_code == 307
        assert page.headers["location"].startswith("/auth/login")


def test_openapi_contract_is_public_but_does_not_bypass_data_auth(monkeypatch) -> None:
    configure_auth(monkeypatch)
    with TestClient(app) as client:
        contract = client.get("/openapi.json")
        api = client.get("/clients")

    assert contract.status_code == 200
    assert "/clients/{client_id}/subscription" in contract.json()["paths"]
    assert api.status_code == 401


def test_valid_server_side_session_allows_owner_and_origin_protects_posts(monkeypatch) -> None:
    configure_auth(monkeypatch)
    token = owner_cookie()
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, token)
        session = client.get("/auth/session")
        blocked = client.post(
            "/clients",
            json={"business_name": "CSRF Blocked", "service_start_date": "2026-08-13"},
        )
        allowed = client.post(
            "/clients",
            headers={"Origin": "http://testserver"},
            json={"business_name": "CSRF Allowed", "service_start_date": "2026-08-13"},
        )

    assert session.json() == {"authenticated": True, "email": OWNER_EMAIL}
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "csrf_origin_invalid"
    assert allowed.status_code == 201


def test_owner_login_reuses_google_callback_and_sets_secure_session(monkeypatch) -> None:
    configure_auth(monkeypatch)
    with TestClient(app) as client:
        start = client.get("/auth/login?next=/dashboard/tasks/approvals", follow_redirects=False)
        query = parse_qs(urlparse(start.headers["location"]).query)
        state = query["state"][0]
        assert set(query["scope"][0].split()) == {"openid", "email", "profile"}
        assert query["nonce"][0]
        monkeypatch.setattr(
            google_oauth,
            "_exchange_code_for_tokens",
            lambda *args: {"id_token": "signed-owner-id-token"},
        )
        monkeypatch.setattr(
            google_oauth,
            "verify_owner_id_token",
            lambda id_token, nonce_hash: OWNER_EMAIL,
        )
        callback = client.get(
            f"/google/oauth/callback?code=owner-code&state={state}",
            follow_redirects=False,
        )

    assert callback.status_code == 303
    assert callback.headers["location"] == "/dashboard/tasks/approvals"
    assert SESSION_COOKIE in callback.headers["set-cookie"]
    assert "HttpOnly" in callback.headers["set-cookie"]
    assert "SameSite=lax" in callback.headers["set-cookie"]


def test_expired_or_removed_owner_session_is_rejected(monkeypatch) -> None:
    configure_auth(monkeypatch)
    token = owner_cookie()
    with SessionLocal() as database:
        session = database.query(models.OwnerSession).filter_by(token_hash=digest(token)).one()
        session.expires_at = datetime.utcnow() - timedelta(seconds=1)
        database.commit()
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, token)
        response = client.get("/clients")

    assert response.status_code == 401
