"""Tests for the app live here."""

def test_health() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    # TestClient lets us call the app without starting a real server.
    with TestClient(app) as client:
        # Send a fake GET request to the health endpoint.
        response = client.get("/health")

    # The endpoint should respond successfully.
    assert response.status_code == 200

    # The body should match the simple health payload.
    assert response.json() == {"status": "ok"}
