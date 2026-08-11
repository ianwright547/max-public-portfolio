"""Website builds begin as evidence-backed approval tasks, never direct execution."""

from fastapi.testclient import TestClient

from app.main import app
from tests.test_profile_approval import make_proposal


def test_website_generation_requires_official_profile_and_creates_task_after_approval() -> None:
    with TestClient(app) as client:
        client_id, data = make_proposal(client, "Website Generation")
        blocked = client.post(
            f"/clients/{client_id}/website-generation-task",
            json={"requested_outcome": "Build the approved client website.", "requested_by": "Agency Owner"},
        )
        assert client.post(
            f"/profile-versions/{data['version_id']}/decision",
            json={"decision": "approve", "decision_maker": "Agency Owner"},
        ).status_code == 200
        created = client.post(
            f"/clients/{client_id}/website-generation-task",
            json={"mode": "replicate", "requested_outcome": "Build the approved client website.", "requested_by": "Agency Owner"},
        )
        duplicate = client.post(
            f"/clients/{client_id}/website-generation-task",
            json={"requested_outcome": "Build the approved client website.", "requested_by": "Agency Owner"},
        )
        pending = client.get("/tasks/pending-approval")

    assert blocked.status_code == 409
    assert created.status_code == 201
    task = created.json()
    assert task["client_id"] == client_id
    assert task["status"] == "proposed"
    assert task["risk"] == "high"
    assert task["required_access"] == ["GitHub repository", "Vercel project", "client domain"]
    assert duplicate.status_code == 409
    assert any(item["id"] == task["id"] for item in pending.json())
