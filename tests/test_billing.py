"""Commercial entitlement and signed subscription webhook coverage."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.auth_service import SESSION_COOKIE, create_owner_session
from app.database import SessionLocal


def _signed(payload: dict, secret: str) -> tuple[str, str]:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw.decode(), signature


def test_owner_can_create_and_read_a_subscription() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/clients",
            json={"business_name": "Billing Client", "service_start_date": "2026-08-05"},
        ).json()
        response = client.put(
            f"/clients/{created['id']}/subscription",
            json={"status": "active", "plan": "growth", "provider": "manual"},
        )
        read = client.get(f"/clients/{created['id']}/subscription")

    assert response.status_code == 200
    assert read.status_code == 200
    assert read.json()["status"] == "active"
    assert read.json()["plan"] == "growth"


def test_subscription_routes_require_owner_auth_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret-with-enough-entropy")
    monkeypatch.setenv("MAX_ALLOWED_GOOGLE_EMAILS", "owner@example.com")
    monkeypatch.setenv("MAX_REQUIRE_AUTH", "true")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "owner-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "owner-client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://testserver/google/oauth/callback")
    monkeypatch.setenv("MAX_REQUIRE_AUTH", "false")
    monkeypatch.setenv("AUTH_SECRET", "")
    monkeypatch.setenv("MAX_ALLOWED_GOOGLE_EMAILS", "")
    with TestClient(app) as client:
        created = client.post(
            "/clients",
            json={"business_name": "Protected Billing Client", "service_start_date": "2026-08-05"},
        ).json()
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret-with-enough-entropy")
    monkeypatch.setenv("MAX_ALLOWED_GOOGLE_EMAILS", "owner@example.com")
    monkeypatch.setenv("MAX_REQUIRE_AUTH", "true")
    with TestClient(app) as client:
        assert client.get(f"/clients/{created['id']}/subscription").status_code == 401
        assert client.put(
            f"/clients/{created['id']}/subscription",
            json={"status": "active", "plan": "growth", "provider": "manual"},
        ).status_code == 401
        with SessionLocal() as database:
            _session, token = create_owner_session(database, "owner@example.com")
        client.cookies.set(SESSION_COOKIE, token)
        assert client.get(f"/clients/{created['id']}/subscription").status_code == 404
        response = client.put(
            f"/clients/{created['id']}/subscription",
            headers={"Origin": "http://testserver"},
            json={"status": "active", "plan": "growth", "provider": "manual"},
        )
        assert response.status_code == 200


def test_signed_billing_webhook_is_idempotent_and_rejects_payload_replay(monkeypatch) -> None:
    secret = "billing-webhook-secret"
    monkeypatch.setenv("BILLING_WEBHOOK_SECRET", secret)
    with TestClient(app) as client:
        created = client.post(
            "/clients",
            json={"business_name": "Webhook Billing Client", "service_start_date": "2026-08-05"},
        ).json()
        payload = {
            "event_id": "evt_subscription_1",
            "event_type": "subscription.active",
            "client_id": created["id"],
            "provider": "test-provider",
            "status": "active",
            "plan": "agency",
            "current_period_end": (datetime.utcnow() + timedelta(days=30)).isoformat(),
        }
        raw, signature = _signed(payload, secret)
        first = client.post("/billing/webhook", content=raw, headers={"X-Billing-Signature": signature})
        replay = client.post("/billing/webhook", content=raw, headers={"X-Billing-Signature": signature})
        changed = {**payload, "status": "cancelled"}
        changed_raw, changed_signature = _signed(changed, secret)
        mismatch = client.post(
            "/billing/webhook", content=changed_raw, headers={"X-Billing-Signature": changed_signature}
        )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"] == "subscription_event_payload_mismatch"


def test_billing_readiness_requires_contract_when_enforcement_is_enabled(monkeypatch) -> None:
    from app.readiness_service import build_readiness
    from app.database import SessionLocal

    monkeypatch.setenv("MAX_BILLING_ENFORCEMENT", "true")
    monkeypatch.delenv("BILLING_PROVIDER", raising=False)
    monkeypatch.delenv("BILLING_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr("app.readiness_service.expected_migration_revision", lambda: "head_revision")
    monkeypatch.setattr("app.readiness_service.current_migration_revision", lambda database: "head_revision")
    with SessionLocal() as database:
        result = build_readiness(database, "full")

    billing = next(item for item in result["checks"] if item["key"] == "billing_contract")
    assert billing["status"] == "blocked"


def test_fulfillment_entitlement_fails_closed_only_in_paid_mode(monkeypatch) -> None:
    from fastapi import HTTPException
    from app.database import SessionLocal
    from app.subscription_service import require_fulfillment_entitlement

    with TestClient(app) as client:
        created = client.post(
            "/clients",
            json={"business_name": "Entitlement Client", "service_start_date": "2026-08-05"},
        ).json()
    monkeypatch.setenv("MAX_BILLING_ENFORCEMENT", "true")
    with SessionLocal() as database:
        try:
            require_fulfillment_entitlement(database, created["id"])
        except HTTPException as error:
            assert error.status_code == 402
        else:
            raise AssertionError("missing subscription must block paid-mode fulfillment")


def test_paid_mode_blocks_new_reports_and_daily_plans_but_not_client_creation(monkeypatch) -> None:
    monkeypatch.setenv("MAX_BILLING_ENFORCEMENT", "true")
    with TestClient(app) as client:
        created = client.post(
            "/clients",
            json={"business_name": "Paid Boundary Client", "service_start_date": "2026-08-05"},
        ).json()
        report = client.post(
            f"/clients/{created['id']}/reports",
            json={
                "report_type": "internal",
                "period_start": "2026-08-01",
                "period_end": "2026-08-31",
                "generated_by": "Owner",
            },
        )
        plan = client.post(
            f"/clients/{created['id']}/daily-plan",
            json={"depth": "simple", "focus": "all", "created_by": "Owner"},
        )

    assert report.status_code == 402
    assert report.json()["detail"]["code"] == "billing_subscription_required"
    assert plan.status_code == 402
    assert plan.json()["detail"]["code"] == "billing_subscription_required"
