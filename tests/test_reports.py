"""Phase 11 tests for truthful, client-separated report snapshots."""

from tests.test_fulfillment import make_eligible_task, simulation
from tests.test_health_checks import make_health_client
from tests.test_verifications import review_payload


def report_request(report_type: str = "client") -> dict:
    return {
        "report_type": report_type,
        "period_start": "2026-08-01",
        "period_end": "2026-08-31",
        "generated_by": "Test Owner",
    }


def test_unverified_work_never_appears_as_completed() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id, _, task_id = make_eligible_task(client, "Unverified Report Work", ready=True)
        execution = client.post(
            f"/tasks/{task_id}/simulated-executions",
            json=simulation("unverified-report-execution"),
        ).json()
        report = client.post(f"/clients/{client_id}/reports", json=report_request())
        html = client.get(f"/reports/{report.json()['id']}/html")

        client.post(
            f"/executions/{execution['id']}/verifications",
            json=review_payload("report-work-verification"),
        )
        verified_report = client.post(f"/clients/{client_id}/reports", json=report_request())

    assert report.json()["snapshot_data"]["verified_work"] == []
    assert "No work was independently verified" in html.text
    assert len(verified_report.json()["snapshot_data"]["verified_work"]) == 1
    assert verified_report.json()["snapshot_data"]["verified_work"][0]["task_id"] == task_id


def test_mock_metrics_are_visibly_labeled_and_negative_changes_are_not_hidden() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "Mock Report Labels")
        client.post(
            f"/clients/{client_id}/metrics",
            json={"metric_name": "calls", "value": 40, "measurement_period": "2026-07", "source_type": "manual", "is_baseline": True},
        )
        client.post(
            f"/clients/{client_id}/metrics/mock",
            json={"measurement_period": "2026-08"},
        )
        report = client.post(f"/clients/{client_id}/reports", json=report_request())
        html = client.get(f"/reports/{report.json()['id']}/html")

    call_fact = next(
        item for item in report.json()["snapshot_data"]["metrics"] if item["metric_name"] == "calls"
    )
    assert call_fact["baseline"]["source_label"] == "Manual data"
    assert call_fact["current"]["source_label"] == "Mock data"
    assert "Mock data" in html.text
    assert "Manual data" in html.text
    assert "decreased" in html.text or "increased" in html.text or "did not change" in html.text


def test_reports_never_mix_client_data() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        first_id = make_health_client(client, "First Report Client")
        second_id = make_health_client(client, "Second Report Client")
        client.post(
            f"/clients/{first_id}/metrics",
            json={"metric_name": "calls", "value": 12, "measurement_period": "2026-08", "source_type": "manual"},
        )
        client.post(
            f"/clients/{second_id}/metrics",
            json={"metric_name": "calls", "value": 987654, "measurement_period": "2026-08", "source_type": "imported"},
        )
        first_report = client.post(f"/clients/{first_id}/reports", json=report_request("internal"))
        second_report = client.post(f"/clients/{second_id}/reports", json=report_request("internal"))
        first_html = client.get(f"/reports/{first_report.json()['id']}/html")

    first_metrics = first_report.json()["snapshot_data"]["metrics"]
    second_metrics = second_report.json()["snapshot_data"]["metrics"]
    assert {item["current"]["value"] for item in first_metrics} == {12}
    assert {item["current"]["value"] for item in second_metrics} == {987654}
    assert "987654" not in first_html.text
    assert first_report.json()["client_id"] == first_id
    assert second_report.json()["client_id"] == second_id


def test_report_snapshot_does_not_change_when_new_results_are_added() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "Immutable Report")
        client.post(
            f"/clients/{client_id}/metrics",
            json={"metric_name": "calls", "value": 20, "measurement_period": "2026-07", "source_type": "manual"},
        )
        created = client.post(f"/clients/{client_id}/reports", json=report_request())
        client.post(
            f"/clients/{client_id}/metrics",
            json={"metric_name": "calls", "value": 99, "measurement_period": "2026-08", "source_type": "imported"},
        )
        saved = client.get(f"/reports/{created.json()['id']}")

    metric = saved.json()["snapshot_data"]["metrics"][0]
    assert metric["current"]["value"] == 20
    assert metric["current"]["source_label"] == "Manual data"


def test_client_report_pdf_requires_approval_and_is_valid_pdf() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "PDF Report")
        created = client.post(f"/clients/{client_id}/reports", json=report_request()).json()
        blocked = client.get(f"/reports/{created['id']}/pdf")
        approved = client.post(
            f"/reports/{created['id']}/approval", json={"approved_by": "Agency Owner"}
        )
        pdf = client.get(f"/reports/{created['id']}/pdf")

    assert blocked.status_code == 409
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-1.4")
    assert b"Client Progress" in pdf.content


def test_simple_report_includes_tangible_plan_and_expected_result() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "Planned PDF Report")
        created = client.post(
            f"/clients/{client_id}/reports",
            json={**report_request(), "update_mode": "simple"},
        ).json()
        html = client.get(f"/reports/{created['id']}/html")
        client.post(f"/reports/{created['id']}/approval", json={"approved_by": "Agency Owner"})
        pdf = client.get(f"/reports/{created['id']}/pdf")

    assert "client_update" in created["snapshot_data"]
    assert "Action plan and expected results" in html.text
    assert "Expected result:" in html.text
    assert "Evidence provenance" in html.text
    assert created["snapshot_data"]["evidence_provenance"]
    first_plan_item = created["snapshot_data"]["client_update"]["plan_30"][0]
    assert first_plan_item["success_metric"]
    assert first_plan_item["verification_window"]
    assert first_plan_item["evidence_provenance"]["source"]
    assert pdf.status_code == 200
    assert b"Action plan and expected results" in pdf.content
    assert b"Success metric:" in pdf.content


def test_in_depth_client_pdf_contains_plan_and_approval_gated_message() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "Shareable In Depth PDF")
        created = client.post(
            f"/clients/{client_id}/reports",
            json={**report_request(), "update_mode": "in_depth"},
        ).json()
        client.post(
            f"/reports/{created['id']}/approval", json={"approved_by": "Agency Owner"}
        )
        pdf = client.get(f"/reports/{created['id']}/pdf")

    assert pdf.status_code == 200
    assert b"Action plan and expected results" in pdf.content
    assert b"Draft client message" in pdf.content
    assert b"requires owner approval" in pdf.content
    assert b"Expected result:" in pdf.content
    assert b"Evidence provenance" in pdf.content


def test_internal_report_includes_tangible_plan_for_owner_operations() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "Internal Planned Report")
        created = client.post(
            f"/clients/{client_id}/reports",
            json={**report_request("internal"), "update_mode": "in_depth"},
        ).json()
        html = client.get(f"/reports/{created['id']}/html")

    assert "client_update" in created["snapshot_data"]
    assert "Action plan and expected results" in html.text
    assert "Expected result:" in html.text
    assert "What is needed to continue" in html.text


def test_report_plan_item_becomes_an_approval_gated_task_and_is_idempotent() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "Report Task Bridge")
        report = client.post(
            f"/clients/{client_id}/reports",
            json={**report_request("internal"), "update_mode": "simple"},
        ).json()
        first = client.post(
            f"/reports/{report['id']}/plan-items/plan_30/0/task",
            json={"created_by": "Agency Owner", "estimated_effort": "30 minutes", "risk": "low"},
        )
        replay = client.post(
            f"/reports/{report['id']}/plan-items/plan_30/0/task",
            json={"created_by": "Agency Owner", "estimated_effort": "30 minutes", "risk": "low"},
        )
        from app import models
        from app.database import SessionLocal
        with SessionLocal() as database:
            finding = database.get(models.Finding, first.json()["source_finding_id"])

    assert first.status_code == 201
    assert first.json()["status"] == "proposed"
    assert finding is not None
    assert finding.source == "report_plan"
    assert finding.evidence["report_id"] == report["id"]
    assert finding.evidence["success_metric"]
    assert finding.evidence["evidence_provenance"]
    assert first.json()["expected_result"]
    assert first.json()["success_metric"] == finding.evidence["success_metric"]
    assert first.json()["verification_window"]
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]


def test_reports_include_operational_retention_risk_and_approval_gated_client_message() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "Retention Summary Client")
        created = client.post(
            f"/clients/{client_id}/reports",
            json={**report_request("internal"), "update_mode": "in_depth"},
        ).json()
        html = client.get(f"/reports/{created['id']}/html")
        client_report = client.post(
            f"/clients/{client_id}/reports",
            json={**report_request(), "update_mode": "in_depth"},
        ).json()
        client_html = client.get(f"/reports/{client_report['id']}/html")

    snapshot = created["snapshot_data"]
    assert snapshot["retention_risk"]["level"] in {"low", "medium", "high"}
    assert snapshot["retention_risk"]["reasons"]
    assert snapshot["client_message"].startswith("Hi Retention Summary Client")
    assert "Retention-risk summary" in html.text
    assert "Draft client message" in html.text
    assert "requires owner approval" in html.text
    assert "Draft client message" in client_html.text
    assert "Retention-risk summary" not in client_html.text
    assert "Operational value risk" not in client_html.text
    assert "Recorded execution cost" not in client_html.text


def test_client_message_does_not_expose_internal_risk_label() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "Safe Client Message")
        created = client.post(
            f"/clients/{client_id}/reports",
            json={**report_request(), "update_mode": "simple"},
        ).json()

    message = created["snapshot_data"]["client_message"]
    assert "retention" not in message.casefold()
    assert "Operational value risk" not in message


def test_client_failure_renderer_suppresses_internal_diagnostics() -> None:
    from app.report_builder import client_safe_failure_detail

    safe = client_safe_failure_detail({"detail": "Search Console access needs to be reconnected."})
    secret = client_safe_failure_detail({"detail": "provider exception: Authorization Bearer access_token=secret"})

    assert safe == "Search Console access needs to be reconnected."
    assert "secret" not in secret.casefold()
    assert "exception" not in secret.casefold()
    assert "reviewing" in secret


def test_report_slack_delivery_requires_approved_client_report(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.test_slack import FakeSlackAdapter, connect_fake_slack

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    with TestClient(app) as client:
        client_id = make_health_client(client, "Report Delivery Gates")
        client.post(f"/clients/{client_id}/slack-channel")
        draft = client.post(f"/clients/{client_id}/reports", json=report_request()).json()
        blocked_draft = client.post(f"/reports/{draft['id']}/slack-delivery")
        internal = client.post(
            f"/clients/{client_id}/reports", json=report_request("internal")
        ).json()
        client.post(f"/reports/{internal['id']}/approval", json={"approved_by": "Agency Owner"})
        blocked_internal = client.post(f"/reports/{internal['id']}/slack-delivery")

    assert blocked_draft.status_code == 409
    assert blocked_draft.json()["detail"] == "report_approval_required"
    assert blocked_internal.status_code == 409
    assert blocked_internal.json()["detail"] == "client_report_required"
    assert adapter.messages == []


def test_approved_report_slack_delivery_is_client_bound_and_idempotent(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.test_slack import FakeSlackAdapter, connect_fake_slack

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("MAX_PUBLIC_BASE_URL", "https://max.example.test/")
    with TestClient(app) as client:
        client_id = make_health_client(client, "Delivered Report Client")
        connection = client.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        report = client.post(f"/clients/{client_id}/reports", json=report_request()).json()
        client.post(f"/reports/{report['id']}/approval", json={"approved_by": "Agency Owner"})
        first = client.post(f"/reports/{report['id']}/slack-delivery")
        second = client.post(f"/reports/{report['id']}/slack-delivery")

    assert first.status_code == 200
    assert first.json()["status"] == "delivered"
    assert first.json()["client_id"] == client_id
    assert first.json()["channel_id"] == connection["channel_id"]
    assert first.json()["attempt_count"] == 1
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["attempt_count"] == 1
    assert len(adapter.messages) == 1
    assert adapter.messages[0]["channel_id"] == connection["channel_id"]
    assert f"https://max.example.test/reports/{report['id']}/share/" in adapter.messages[0]["text"]


def test_client_report_share_is_public_approved_expiring_and_revocable(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.test_slack import FakeSlackAdapter, connect_fake_slack

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("MAX_PUBLIC_BASE_URL", "https://max.example.test")
    with TestClient(app) as client:
        client_id = make_health_client(client, "Share Link Client")
        client.post(f"/clients/{client_id}/slack-channel")
        report = client.post(f"/clients/{client_id}/reports", json=report_request()).json()
        client.post(f"/reports/{report['id']}/approval", json={"approved_by": "Agency Owner"})
        delivered = client.post(f"/reports/{report['id']}/slack-delivery")
        assert delivered.status_code == 200
        share_url = adapter.messages[0]["text"].split("Download the approved PDF: ", 1)[1].split("\n", 1)[0]
        share_path = share_url.replace("https://max.example.test", "")
        shared = client.get(share_path)
        tampered = client.get(share_path[:-1] + ("0" if share_path[-1] != "0" else "1"))
        revoked = client.post(f"/reports/{report['id']}/share/revoke")
        after_revoke = client.get(share_path)

    assert shared.status_code == 200
    assert shared.headers["content-type"] == "application/pdf"
    assert tampered.status_code == 404
    assert revoked.status_code == 200
    assert revoked.json() == {"report_id": report["id"], "revoked": True}
    assert after_revoke.status_code == 404


def test_paid_mode_blocks_delivery_of_an_approved_report(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.test_slack import FakeSlackAdapter, connect_fake_slack

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("MAX_PUBLIC_BASE_URL", "https://max.example.test")
    with TestClient(app) as client:
        client_id = make_health_client(client, "Paid Report Delivery")
        client.post(f"/clients/{client_id}/slack-channel")
        report = client.post(f"/clients/{client_id}/reports", json=report_request()).json()
        client.post(f"/reports/{report['id']}/approval", json={"approved_by": "Agency Owner"})
        monkeypatch.setenv("MAX_BILLING_ENFORCEMENT", "true")
        response = client.post(f"/reports/{report['id']}/slack-delivery")

    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "billing_subscription_required"
    assert adapter.messages == []


def test_failed_report_delivery_retries_same_record(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.test_slack import FakeSlackAdapter, connect_fake_slack

    adapter = FakeSlackAdapter(fail_messages=True)
    connect_fake_slack(monkeypatch, adapter)
    with TestClient(app) as client:
        client_id = make_health_client(client, "Report Delivery Retry")
        client.post(f"/clients/{client_id}/slack-channel")
        report = client.post(f"/clients/{client_id}/reports", json=report_request()).json()
        client.post(f"/reports/{report['id']}/approval", json={"approved_by": "Agency Owner"})
        failed = client.post(f"/reports/{report['id']}/slack-delivery")
        adapter.fail_messages = False
        retried = client.post(f"/reports/{report['id']}/slack-delivery")

    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert failed.json()["last_error"] == "slack_temporarily_unavailable"
    assert retried.status_code == 200
    assert retried.json()["id"] == failed.json()["id"]
    assert retried.json()["status"] == "delivered"
    assert retried.json()["attempt_count"] == 2
    assert len(adapter.messages) == 1


def test_report_page_drives_approval_delivery_and_shows_audit_history(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app import models
    from app.database import SessionLocal
    from app.main import app
    from tests.test_slack import FakeSlackAdapter, connect_fake_slack

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    with TestClient(app) as client:
        client_id = make_health_client(client, "Report Owner Workflow")
        client.post(f"/clients/{client_id}/slack-channel")
        report = client.post(f"/clients/{client_id}/reports", json=report_request()).json()
        draft_page = client.get(f"/reports/{report['id']}/html")
        approval = client.post(
            f"/dashboard/reports/{report['id']}/approval",
            data={"approved_by": "Dashboard Owner"},
            follow_redirects=False,
        )
        approved_page = client.get(approval.headers["location"])
        delivery = client.post(
            f"/dashboard/reports/{report['id']}/slack-delivery",
            follow_redirects=False,
        )
        delivered_page = client.get(delivery.headers["location"])
        with SessionLocal() as database:
            events = list(
                database.scalars(
                    select(models.AuditEvent)
                    .where(
                        models.AuditEvent.record_type == "report",
                        models.AuditEvent.record_id == report["id"],
                    )
                    .order_by(models.AuditEvent.created_at, models.AuditEvent.id)
                )
            )

    assert "Approve client report" in draft_page.text
    assert approval.status_code == 303
    assert "Report approved" in approved_page.text
    assert "Deliver to client Slack channel" in approved_page.text
    assert delivery.status_code == 303
    assert "Report delivered" in delivered_page.text
    assert "Audit history (2)" in delivered_page.text
    assert "Dashboard Owner" in delivered_page.text
    assert {event.event_type for event in events} == {
        "report_approved",
        "report_delivery_succeeded",
    }
