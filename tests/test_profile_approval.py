"""Phase 16 tests for human profile approval and version history."""

from tests.test_interpretations import make_client, make_intake
from fastapi.testclient import TestClient

from app.main import app


def make_proposal(client: TestClient, label: str = "Approval") -> tuple[str, dict]:
    client_id = make_client(client, label)
    intake = make_intake(client, client_id)
    proposal = client.post(f"/intakes/{intake['id']}/interpret").json()
    version_id = client.get(f"/interpretations/{proposal['id']}/versions").json()[0]["id"]
    return client_id, {"proposal": proposal, "version_id": version_id, "intake_id": intake["id"]}


def test_approval_creates_official_profile() -> None:
    with TestClient(app) as client:
        client_id, data = make_proposal(client)
        decision = client.post(
            f"/profile-versions/{data['version_id']}/decision",
            json={"decision": "approve", "decision_maker": "Agency Owner", "reason": "Reviewed"},
        )
        official = client.get(f"/clients/{client_id}/official-profile")

    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"
    assert official.status_code == 200
    assert official.json()["approved_version_id"] == data["version_id"]


def test_rejection_requires_reason_and_does_not_create_official_profile() -> None:
    with TestClient(app) as client:
        client_id, data = make_proposal(client, "Reject")
        missing_reason = client.post(
            f"/profile-versions/{data['version_id']}/decision",
            json={"decision": "reject", "decision_maker": "Agency Owner"},
        )
        rejected = client.post(
            f"/profile-versions/{data['version_id']}/decision",
            json={"decision": "reject", "decision_maker": "Agency Owner", "reason": "Phone needs correction"},
        )
        official = client.get(f"/clients/{client_id}/official-profile")

    assert missing_reason.status_code == 422
    assert rejected.json()["status"] == "rejected"
    assert official.status_code == 404


def test_rejected_version_correction_preserves_previous_version() -> None:
    with TestClient(app) as client:
        _, data = make_proposal(client, "Correction")
        client.post(
            f"/profile-versions/{data['version_id']}/decision",
            json={"decision": "reject", "decision_maker": "Agency Owner", "reason": "Needs correction"},
        )
        corrected = client.post(
            f"/profile-versions/{data['version_id']}/correct",
            json={"decision_maker": "Agency Owner", "profile_data": {"contact_information": {"email": "fixed@example.com"}}},
        )
        previous = client.get(f"/profile-versions/{data['version_id']}").json()

    assert corrected.status_code == 201
    assert corrected.json()["version_number"] == 2
    assert corrected.json()["status"] == "pending"
    assert previous["status"] == "rejected"


def test_forbidden_state_changes_are_rejected() -> None:
    with TestClient(app) as client:
        _, data = make_proposal(client, "State")
        approved = client.post(
            f"/profile-versions/{data['version_id']}/decision",
            json={"decision": "approve", "decision_maker": "Agency Owner"},
        )
        again = client.post(
            f"/profile-versions/{data['version_id']}/decision",
            json={"decision": "approve", "decision_maker": "Agency Owner"},
        )
        correction = client.post(
            f"/profile-versions/{data['version_id']}/correct",
            json={"decision_maker": "Agency Owner", "profile_data": {}},
        )

    assert approved.status_code == 200
    assert again.status_code == 409
    assert correction.status_code == 409


def test_approval_cannot_cross_clients() -> None:
    with TestClient(app) as client:
        first_id, first = make_proposal(client, "First approval")
        second_id, second = make_proposal(client, "Second approval")
        approved = client.post(
            f"/profile-versions/{first['version_id']}/decision",
            json={"decision": "approve", "decision_maker": "Agency Owner"},
        )
        first_official = client.get(f"/clients/{first_id}/official-profile")
        second_official = client.get(f"/clients/{second_id}/official-profile")

    assert approved.json()["client_id"] == first_id
    assert first_official.status_code == 200
    assert second_official.status_code == 404
