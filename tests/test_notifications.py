"""Phase 12 tests for meaningful, deduplicated internal notifications."""

from tests.test_fulfillment import make_eligible_task, simulation
from tests.test_health_checks import add_calls, add_intake, make_health_client
from tests.test_reports import report_request
from tests.test_verifications import review_payload


def categories(client, client_id: str) -> list[str]:
    return [item["category"] for item in client.get(f"/notifications?client_id={client_id}").json()]


def test_healthy_checks_routine_success_and_small_changes_stay_quiet() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        health_client = make_health_client(client, "Quiet Healthy Client")
        add_intake(client, health_client)
        add_calls(client, health_client, 100, 95)
        client.post(f"/clients/{health_client}/health-checks", json={"website_status": "available"})

        task_client, _, task_id = make_eligible_task(client, "Quiet Routine Success", ready=True)
        before_execution = categories(client, task_client)
        client.post(
            f"/tasks/{task_id}/simulated-executions",
            json=simulation("quiet-routine-execution", estimated_cost=0.25),
        )
        after_execution = categories(client, task_client)

    assert categories(client, health_client) == []
    assert after_execution == before_execution
    assert "task_failure" not in after_execution
    assert "cost_threshold_exceeded" not in after_execution


def test_critical_health_missing_access_and_duplicate_findings_follow_rules() -> None:
    from fastapi.testclient import TestClient

    from app import models
    from app.database import SessionLocal
    from app.main import app

    with TestClient(app) as client:
        critical_client = make_health_client(client, "Critical Notification")
        add_intake(client, critical_client)
        add_calls(client, critical_client, 100, 105)
        client.post(f"/clients/{critical_client}/health-checks", json={"website_status": "unavailable"})
        client.post(f"/clients/{critical_client}/health-checks", json={"website_status": "unavailable"})

        access_client = make_health_client(client, "Access Notification")
        add_intake(client, access_client)
        add_calls(client, access_client, 100, 105)
        with SessionLocal() as database:
            database.add(
                models.IntegrationConnection(
                    client_id=access_client,
                    integration_name="Google Business Profile",
                    connection_status="missing_permission",
                    data_source_type="manual",
                    issues=["Manager access required"],
                )
            )
            database.commit()
        client.post(f"/clients/{access_client}/health-checks", json={"website_status": "available"})
        client.post(f"/clients/{access_client}/health-checks", json={"website_status": "available"})

    assert categories(client, critical_client).count("critical_health_issue") == 1
    assert categories(client, access_client).count("missing_required_access") == 1


def test_approval_failure_verification_cost_performance_and_scheduled_report_notifications() -> None:
    from fastapi.testclient import TestClient

    from app import models
    from app.database import SessionLocal
    from app.main import app

    with TestClient(app) as client:
        failure_client, _, failure_task = make_eligible_task(client, "Failure Notifications", ready=True)
        client.post(
            f"/tasks/{failure_task}/simulated-executions",
            json=simulation(
                "failure-notification-execution",
                outcome="failure",
                failure_type="permanent",
                estimated_cost=6.0,
            ),
        )

        verification_client, _, verification_task = make_eligible_task(
            client, "Verification Notification", ready=True
        )
        execution = client.post(
            f"/tasks/{verification_task}/simulated-executions",
            json=simulation("verification-notification-execution"),
        ).json()
        with SessionLocal() as database:
            saved = database.get(models.FulfillmentExecution, execution["id"])
            saved.simulated_test_results = [
                {"name": "simulated task check", "status": "failed", "simulated": True}
            ]
            database.commit()
        client.post(
            f"/executions/{execution['id']}/verifications",
            json=review_payload(
                "verification-notification-decision",
                "verification_failed",
                "The saved test failed.",
            ),
        )

        metric_client = make_health_client(client, "Performance Notification")
        for period, value in [("2026-06", 100), ("2026-07", 95), ("2026-08", 40), ("2026-08", 39)]:
            client.post(
                f"/clients/{metric_client}/metrics",
                json={"metric_name": "calls", "value": value, "measurement_period": period, "source_type": "manual"},
            )

        report_client = make_health_client(client, "Scheduled Report Notification")
        manual_request = report_request()
        client.post(f"/clients/{report_client}/reports", json=manual_request)
        scheduled_request = {**manual_request, "generation_reason": "scheduled"}
        client.post(f"/clients/{report_client}/reports", json=scheduled_request)

    failure_categories = categories(client, failure_client)
    assert "approval_required" in failure_categories
    assert "task_failure" in failure_categories
    assert "cost_threshold_exceeded" in failure_categories
    assert "verification_failure" in categories(client, verification_client)
    assert categories(client, metric_client).count("meaningful_performance_change") == 1
    assert categories(client, report_client).count("scheduled_report_available") == 1


def test_notification_filters_and_read_state_preserve_client_separation() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        first_id = make_health_client(client, "First Notification Client")
        second_id = make_health_client(client, "Second Notification Client")
        for client_id, last_value in [(first_id, 40), (second_id, 150)]:
            client.post(
                f"/clients/{client_id}/metrics",
                json={"metric_name": "calls", "value": 100, "measurement_period": "2026-07", "source_type": "manual"},
            )
            client.post(
                f"/clients/{client_id}/metrics",
                json={"metric_name": "calls", "value": last_value, "measurement_period": "2026-08", "source_type": "manual"},
            )
        first_notifications = client.get(f"/notifications?client_id={first_id}").json()
        second_notifications = client.get(f"/notifications?client_id={second_id}").json()
        marked = client.post(f"/notifications/{first_notifications[0]['id']}/read")
        first_unread = client.get(f"/notifications?client_id={first_id}&unread_only=true")
        dashboard = client.get("/dashboard/notifications")

    assert {item["client_id"] for item in first_notifications} == {first_id}
    assert {item["client_id"] for item in second_notifications} == {second_id}
    assert {item["related_record_id"] for item in first_notifications}.isdisjoint(
        {item["related_record_id"] for item in second_notifications}
    )
    assert marked.json()["is_read"] is True
    assert marked.json()["read_at"] is not None
    assert first_unread.json() == []
    assert dashboard.status_code == 200
    assert any(label in dashboard.text for label in ("No Slack connection", "Internal + Slack delivery"))
