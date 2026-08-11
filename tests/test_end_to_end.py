"""End-to-end acceptance coverage for the core Max agency-owner workflow."""

from fastapi.testclient import TestClient

from app.main import app
from tests.test_health_checks import add_calls, add_intake, make_health_client
from tests.test_tasks import approve, change, proposal
from tests.test_verifications import review_payload


def test_core_workflow_runs_from_intake_to_approved_pdf_and_delivery(monkeypatch) -> None:
    from tests.test_slack import FakeSlackAdapter, connect_fake_slack

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    with TestClient(app) as client:
        client_id = make_health_client(client, "End to End")
        intake = client.post(
            f"/clients/{client_id}/intakes",
            json={
                "phone_number": "555-0100",
                "email": "owner@example.com",
                "brand_colors": ["blue"],
                "domain": "https://e2e.example.com",
                "business_hours": "Monday-Friday 9-5",
                "service_areas": ["Chicago"],
                "google_business_profile": "Example profile",
                "enabled_workflows": ["website", "reporting"],
            },
        ).json()
        proposal_response = client.post(f"/intakes/{intake['id']}/interpret").json()
        version = client.get(f"/interpretations/{proposal_response['id']}/versions").json()[0]
        approved_profile = client.post(
            f"/profile-versions/{version['id']}/decision",
            json={"decision": "approve", "decision_maker": "Agency Owner"},
        )

        add_intake(client, client_id)
        add_calls(client, client_id, 100, 105)
        health = client.post(f"/clients/{client_id}/health-checks", json={"website_status": "unavailable"}).json()
        task = client.post(
            f"/clients/{client_id}/tasks", json=proposal(health["findings"][0]["id"])
        ).json()
        assert approve(client, task["id"]).status_code == 200
        execution = client.post(
            f"/tasks/{task['id']}/simulated-executions",
            json={"operation_key": "e2e-execution", "outcome": "success", "estimated_cost": 0.25},
        ).json()
        verification = client.post(
            f"/executions/{execution['id']}/verifications",
            json=review_payload("e2e-verification"),
        )
        client.post(
            f"/clients/{client_id}/metrics",
            json={"metric_name": "calls", "value": 120, "measurement_period": "2026-08", "source_type": "manual"},
        )
        report = client.post(
            f"/clients/{client_id}/reports",
            json={"report_type": "client", "period_start": "2026-08-01", "period_end": "2026-08-31", "generated_by": "Agency Owner"},
        )
        connection = client.post(f"/clients/{client_id}/slack-channel")
        approval = client.post(
            f"/reports/{report.json()['id']}/approval", json={"approved_by": "Agency Owner"}
        )
        pdf = client.get(f"/reports/{report.json()['id']}/pdf")
        delivery = client.post(f"/reports/{report.json()['id']}/slack-delivery")

    assert approved_profile.status_code == 200
    assert execution["status"] == "completed"
    assert verification.status_code == 201
    assert verification.json()["outcome"] == "verified"
    assert report.status_code == 201
    assert approval.status_code == 200
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-1.4")
    assert connection.status_code == 200
    assert delivery.status_code == 200
    assert delivery.json()["status"] == "delivered"
    assert any(
        message["operation_key"] == f"report-delivery:{report.json()['id']}:slack"
        for message in adapter.messages
    )


def test_codex_fulfillment_release_path_reaches_independent_verification() -> None:
    from tests.test_codex_work_packets import link_repository, link_website

    with TestClient(app) as client:
        client_id = make_health_client(client, "Codex Release Path")
        health = client.post(
            f"/clients/{client_id}/health-checks",
            json={"website_status": "unavailable"},
        ).json()
        task = client.post(
            f"/clients/{client_id}/tasks", json=proposal(health["findings"][0]["id"])
        ).json()
        assert approve(client, task["id"]).status_code == 200
        website = link_website(client, client_id, "codex-release-path")
        link_repository(client, client_id, "codex-release-path")
        packet = client.post(
            f"/tasks/{task['id']}/connected-codex-work-packet",
            json={"operation_key": "release-codex-packet", "created_by": "Agency Owner"},
        ).json()
        handed_off = client.post(
            f"/codex-work-packets/{packet['id']}/handoff",
            json={"handed_off_by": "Agency Owner"},
        )
        result = client.post(
            f"/codex-work-packets/{packet['id']}/result",
            json={
                "operation_key": "release-codex-result",
                "outcome": "completed",
                "submitted_by": "Agency Owner",
                "summary": "Completed the scoped website repair.",
                "changed_files": ["app/page.py"],
                "tests": [{"name": "build", "status": "passed"}],
                    "evidence": ["Production URL checked"],
                    "verification_data": {"acceptance_checks": [
                        {"criterion": "requested outcome", "status": "passed", "evidence": "Repair reviewed"},
                        {"criterion": "allowed files", "status": "passed", "evidence": "Packet scope reviewed"},
                        {"criterion": "client target", "status": "passed", "evidence": "Production URL reviewed"},
                    ]},
                },
        )
        execution_id = result.json()["execution"]["id"]
        verification = client.post(
            f"/executions/{execution_id}/verifications",
            json=review_payload("release-codex-verification"),
        )

    assert website["client_id"] == client_id
    assert handed_off.status_code == 200
    assert result.status_code == 200
    assert verification.status_code == 201
    assert verification.json()["outcome"] == "verified"
