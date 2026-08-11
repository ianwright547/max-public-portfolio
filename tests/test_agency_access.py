"""Durable agency-member roles and Slack identity mappings."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from uuid import uuid4

from app import models
from app.auth_service import SESSION_COOKIE, create_owner_session
from app.database import SessionLocal
from app.main import app


def test_owner_can_create_and_update_members_with_unique_slack_mapping() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/agency/members",
            json={
                "email": "operator@example.com",
                "display_name": "Operations",
                "role": "operator",
                "slack_user_id": "U_OPERATOR",
            },
        )
        duplicate_slack = client.post(
            "/agency/members",
            json={
                "email": "viewer@example.com",
                "display_name": "Viewer",
                "role": "viewer",
                "slack_user_id": "U_OPERATOR",
            },
        )
        updated = client.patch(
            f"/agency/members/{created.json()['id']}",
            json={"role": "admin", "display_name": "Operations Lead"},
        )
        listed = client.get("/agency/members")

    assert created.status_code == 201
    assert created.json()["role"] == "operator"
    assert duplicate_slack.status_code == 409
    assert duplicate_slack.json()["detail"] == "agency_member_slack_user_exists"
    assert updated.status_code == 200
    assert updated.json()["role"] == "admin"
    assert updated.json()["display_name"] == "Operations Lead"
    assert any(item["email"] == "operator@example.com" for item in listed.json())


def test_member_dashboard_renders_and_handles_form_submission() -> None:
    suffix = uuid4().hex[:8]
    email = f"dashboard-{suffix}@example.com"
    with TestClient(app) as client:
        page = client.get("/dashboard/agency/members")
        created = client.post(
            "/dashboard/agency/members",
            data={
                "email": email,
                "display_name": "Dashboard Operator",
                "role": "operator",
                "slack_user_id": f"U_DASH_{suffix}",
            },
            follow_redirects=False,
        )
        after = client.get("/dashboard/agency/members")

    assert page.status_code == 200
    assert "Agency members" in page.text
    assert created.status_code == 303
    assert created.headers["location"].startswith("/dashboard/agency/members?message=")
    assert email in after.text
    assert "Dashboard Operator" in after.text


def test_last_active_owner_cannot_be_demoted_or_deactivated() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/agency/members",
            json={
                "email": "only-owner@example.com",
                "display_name": "Only Owner",
                "role": "owner",
            },
        )
        blocked_role = client.patch(
            f"/agency/members/{created.json()['id']}",
            json={"role": "admin"},
        )
        blocked_active = client.patch(
            f"/agency/members/{created.json()['id']}",
            json={"active": False},
        )

    assert created.status_code == 201
    assert blocked_role.status_code == 409
    assert blocked_active.status_code == 409
    assert blocked_role.json()["detail"] == "agency_must_retain_one_active_owner"


def test_operator_member_cannot_manage_members_when_authenticated(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret-with-enough-entropy")
    monkeypatch.setenv("MAX_ALLOWED_GOOGLE_EMAILS", "owner@example.com,operator@example.com")
    monkeypatch.setenv("MAX_REQUIRE_AUTH", "true")
    with SessionLocal() as database:
        member = database.scalar(
            select(models.AgencyMember).where(
                models.AgencyMember.email == "operator@example.com"
            )
        )
        if member is None:
            member = models.AgencyMember(
                email="operator@example.com",
                display_name="Operator",
                role="operator",
                active=True,
            )
            database.add(member)
            database.commit()
        _session, token = create_owner_session(database, "operator@example.com")
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, token)
        response = client.get("/agency/members")

    assert response.status_code == 403
    assert response.json()["detail"] == "agency_role_manage_members_required"


def test_viewer_is_read_only_but_can_access_read_routes(monkeypatch) -> None:
    email = f"viewer-{uuid4().hex[:8]}@example.com"
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret-with-enough-entropy")
    monkeypatch.setenv("MAX_ALLOWED_GOOGLE_EMAILS", f"owner@example.com,{email}")
    monkeypatch.setenv("MAX_REQUIRE_AUTH", "true")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "owner-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "owner-client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://testserver/google/oauth/callback")
    with SessionLocal() as database:
        member = models.AgencyMember(
            email=email,
            display_name="Read Only",
            role="viewer",
            active=True,
        )
        database.add(member)
        database.commit()
        _session, token = create_owner_session(database, email)

    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, token)
        readable = client.get("/clients")
        blocked = client.post(
            "/clients",
            headers={"Origin": "http://testserver"},
            json={"business_name": "Should Not Create", "service_start_date": "2026-08-23"},
        )

    assert readable.status_code == 200
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "agency_role_client_operations_required"
