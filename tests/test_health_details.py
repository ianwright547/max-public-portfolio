"""Operational health signals are safe and actionable."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_details_reports_scheduler_and_onboarding_signals() -> None:
    with TestClient(app) as client:
        response = client.get("/health/details")

    assert response.status_code == 200
    body = response.json()
    assert body["database"] == "ok"
    assert "due_jobs" in body["scheduler"]
    assert "failed_jobs" in body["scheduler"]
    assert "stale_jobs" in body["scheduler"]
    assert "stale_runs" in body["onboarding"]
    assert isinstance(body["alerts"], list)
    assert body["request_id"]
    assert "client" not in str(body).lower()
