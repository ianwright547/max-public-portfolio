"""Phase 15 tests for deterministic onboarding interpretation."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


def make_client(client: TestClient, label: str) -> str:
    return client.post(
        "/clients",
        json={"business_name": f"{label} {uuid4().hex[:8]}", "service_start_date": "2026-08-05"},
    ).json()["id"]


def make_intake(client: TestClient, client_id: str, **overrides: object) -> dict:
    payload = {
        "phone_number": "515-555-0100",
        "email": "owner@example.com",
        "brand_colors": ["#111111", "#3366ff"],
        "domain": "https://example.com",
        "business_hours": "Mon-Fri 9-5",
        "service_areas": ["Demo City"],
        "google_business_profile": "https://google.example/profile",
        "enabled_workflows": ["weekly_report"],
    }
    payload.update(overrides)
    return client.post(f"/clients/{client_id}/intakes", json=payload).json()


def test_complete_intake_creates_structured_proposal_and_preserves_source() -> None:
    with TestClient(app) as client:
        client_id = make_client(client, "Complete interpretation")
        intake = make_intake(client, client_id)
        proposal = client.post(f"/intakes/{intake['id']}/interpret")
        original = client.get(f"/intakes/{intake['id']}")

    assert proposal.status_code == 201
    body = proposal.json()
    assert body["client_id"] == client_id
    assert body["processing_status"] == "ready_for_review"
    assert body["profile_data"]["contact_information"]["email"] == "owner@example.com"
    assert body["missing_information"] == []
    assert original.json()["email"] == "owner@example.com"


def test_missing_information_is_reported_without_invention() -> None:
    from app import models
    from app.database import SessionLocal

    with TestClient(app) as client:
        client_id = make_client(client, "Missing interpretation")
        intake = make_intake(client, client_id)
        with SessionLocal() as database:
            record = database.get(models.Intake, intake["id"])
            record.business_hours = ""
            database.commit()
        proposal = client.post(f"/intakes/{intake['id']}/interpret").json()

    assert proposal["processing_status"] == "needs_review"
    assert "business_hours" in proposal["missing_information"]
    assert proposal["profile_data"]["business_hours"] == ""


def test_conflicting_information_is_reported() -> None:
    with TestClient(app) as client:
        client_id = make_client(client, "Conflict interpretation")
        intake = make_intake(client, client_id, brand_colors=["#111111", "#111111"])
        proposal = client.post(f"/intakes/{intake['id']}/interpret").json()

    assert proposal["processing_status"] == "needs_review"
    assert proposal["conflicting_information"] == ["brand_colors contains duplicate values"]


def test_repeated_processing_reuses_one_proposal() -> None:
    with TestClient(app) as client:
        client_id = make_client(client, "Repeat interpretation")
        intake = make_intake(client, client_id)
        first = client.post(f"/intakes/{intake['id']}/interpret").json()
        second = client.post(f"/intakes/{intake['id']}/interpret").json()

    assert second["id"] == first["id"]


def test_unknown_intake_is_rejected() -> None:
    with TestClient(app) as client:
        response = client.post("/intakes/intake_missing/interpret")

    assert response.status_code == 404


def test_proposals_remain_separated_by_client() -> None:
    with TestClient(app) as client:
        first_id = make_client(client, "First interpretation")
        second_id = make_client(client, "Second interpretation")
        first = make_intake(client, first_id, email="first@example.com")
        second = make_intake(client, second_id, email="second@example.com")
        first_proposal = client.post(f"/intakes/{first['id']}/interpret").json()
        second_proposal = client.post(f"/intakes/{second['id']}/interpret").json()

    assert first_proposal["client_id"] == first_id
    assert second_proposal["client_id"] == second_id
    assert first_proposal["profile_data"]["contact_information"]["email"] == "first@example.com"
    assert second_proposal["profile_data"]["contact_information"]["email"] == "second@example.com"
