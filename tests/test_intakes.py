def make_client(client):
    from uuid import uuid4

    response = client.post(
        "/clients",
        json={
            "business_name": f"Intake Client {uuid4().hex[:8]}",
            "service_start_date": "2026-08-05",
        },
    )
    return response.json()["id"]


def make_intake_payload() -> dict:
    return {
        "phone_number": "555-123-4567",
        "email": "owner@example.com",
        "brand_colors": ["blue", "white"],
        "domain": "example.com",
        "business_hours": "Monday-Friday 9am-5pm",
        "service_areas": ["Dallas", "Fort Worth"],
        "google_business_profile": "Example Business Google Profile",
        "enabled_workflows": ["seo", "reporting"],
    }


def test_submit_onboarding_form() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        client_id = make_client(client)
        response = client.post(f"/clients/{client_id}/intakes", json=make_intake_payload())

    body = response.json()
    assert response.status_code == 201
    assert body["client_id"] == client_id
    assert body["status"] == "received"
    assert body["phone_number"] == "555-123-4567"
    assert body["enabled_workflows"] == ["seo", "reporting"]
    assert body["id"].startswith("intake_")


def test_read_onboarding_form() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        client_id = make_client(client)
        create_response = client.post(f"/clients/{client_id}/intakes", json=make_intake_payload())
        intake_id = create_response.json()["id"]
        read_response = client.get(f"/intakes/{intake_id}")

    assert read_response.status_code == 200
    assert read_response.json()["id"] == intake_id
    assert read_response.json()["client_id"] == client_id


def test_submit_onboarding_form_rejects_unknown_client() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.post("/clients/client_missing/intakes", json=make_intake_payload())

    assert response.status_code == 404
    assert response.json() == {"detail": "Client not found"}


def test_read_unknown_onboarding_form_returns_error() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/intakes/intake_missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Intake not found"}


def test_submit_onboarding_form_rejects_missing_required_information() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    payload = make_intake_payload()
    payload.pop("email")

    with TestClient(app) as client:
        client_id = make_client(client)
        response = client.post(f"/clients/{client_id}/intakes", json=payload)

    assert response.status_code == 422
