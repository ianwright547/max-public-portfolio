"""Prompt compilation keeps approved client context and knowledge traceable."""

from fastapi.testclient import TestClient

from app.main import app


def make_prompt_client(client: TestClient) -> str:
    created = client.post(
        "/clients", json={"business_name": "Prompt Test Business", "service_start_date": "2026-08-13"}
    ).json()
    intake = client.post(
        f"/clients/{created['id']}/intakes",
        json={
            "phone_number": "515-555-0100",
            "email": "owner@example.com",
            "brand_colors": ["#111111"],
            "domain": "https://prompt.example.com",
            "business_hours": "Mon-Fri 9-5",
            "service_areas": ["Demo City"],
            "google_business_profile": "https://google.example/profile",
            "enabled_workflows": ["website_generation"],
        },
    ).json()
    proposal = client.post(f"/intakes/{intake['id']}/interpret").json()
    version = client.get(f"/interpretations/{proposal['id']}/versions").json()[0]
    client.post(
        f"/profile-versions/{version['id']}/decision",
        json={"decision": "approve", "decision_maker": "owner"},
    )
    return created["id"]


def test_prompt_artifact_is_versioned_traceable_and_idempotent() -> None:
    payload = {"operation_key": "prompt-operation-1", "purpose": "website_generation"}
    with TestClient(app) as client:
        client_id = make_prompt_client(client)
        first = client.post(f"/clients/{client_id}/prompt-artifacts", json=payload)
        second = client.post(f"/clients/{client_id}/prompt-artifacts", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    body = first.json()
    assert body["id"] == second.json()["id"]
    assert body["prompt_version"] == "1.0"
    assert "official_profile_id" in body["user_prompt"]
    assert "sops/07-website-generation.md" in body["knowledge_files"]
    assert len(body["content_hash"]) == 64


def test_prompt_artifact_requires_official_profile() -> None:
    with TestClient(app) as client:
        client_id = client.post(
            "/clients", json={"business_name": "No Profile Business", "service_start_date": "2026-08-13"}
        ).json()["id"]
        response = client.post(
            f"/clients/{client_id}/prompt-artifacts",
            json={"operation_key": "prompt-operation-2", "purpose": "reporting"},
        )
    assert response.status_code == 409
    assert response.json()["detail"] == "official_profile_required"


def test_onboarding_prompt_can_use_immutable_intake_before_profile_approval() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/clients", json={"business_name": "Intake Prompt Business", "service_start_date": "2026-08-13"}
        ).json()
        intake = client.post(
            f"/clients/{created['id']}/intakes",
            json={
                "phone_number": "515-555-0100",
                "email": "owner@example.com",
                "brand_colors": ["#111111"],
                "domain": "https://intake-prompt.example.com",
                "business_hours": "Mon-Fri 9-5",
                "service_areas": ["Demo City"],
                "google_business_profile": "https://google.example/profile",
                "enabled_workflows": ["weekly_report"],
            },
        ).json()
        response = client.post(
            f"/clients/{created['id']}/prompt-artifacts",
            json={
                "operation_key": "prompt-operation-intake",
                "purpose": "onboarding_interpretation",
                "intake_id": intake["id"],
            },
        )
    assert response.status_code == 201
    assert response.json()["input_snapshot"]["source_intake"]["domain"] == "https://intake-prompt.example.com"
