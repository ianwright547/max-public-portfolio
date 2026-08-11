"""Phase 8 tests for the safe, idempotent fulfillment simulator."""

from tests.test_tasks import approve, change, make_findings, proposal


def make_eligible_task(client, label: str, ready: bool = False) -> tuple[str, str, str]:
    client_id, findings = make_findings(client, label)
    finding_id = findings[0]["id"]
    task_id = client.post(f"/clients/{client_id}/tasks", json=proposal(finding_id)).json()["id"]
    approve(client, task_id)
    if ready:
        change(client, task_id, "ready")
    return client_id, finding_id, task_id


def simulation(
    operation_key: str,
    outcome: str = "success",
    failure_type=None,
    temporary_failures_before_result: int = 0,
    estimated_cost: float = 0.25,
) -> dict:
    return {
        "operation_key": operation_key,
        "outcome": outcome,
        "failure_type": failure_type,
        "temporary_failures_before_result": temporary_failures_before_result,
        "estimated_cost": estimated_cost,
    }


def test_only_approved_or_ready_tasks_can_enter_simulator() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id, findings = make_findings(client, "Simulator Enforcement")
        proposed_id = client.post(
            f"/clients/{client_id}/tasks", json=proposal(findings[0]["id"])
        ).json()["id"]
        proposed_result = client.post(
            f"/tasks/{proposed_id}/simulated-executions",
            json=simulation("enforcement-proposed"),
        )
        client.post(
            f"/tasks/{proposed_id}/decision",
            json={
                "decision": "rejected",
                "decision_maker": "Agency Owner",
                "reason": "Do not perform this work",
            },
        )
        rejected_result = client.post(
            f"/tasks/{proposed_id}/simulated-executions",
            json=simulation("enforcement-rejected"),
        )

    assert proposed_result.status_code == 409
    assert "approved or ready" in proposed_result.json()["detail"]
    assert rejected_result.status_code == 409
    assert "task is rejected" in rejected_result.json()["detail"]


def test_success_records_cost_evidence_and_completion_without_resolving_finding() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        _, finding_id, task_id = make_eligible_task(client, "Simulator Success")
        response = client.post(
            f"/tasks/{task_id}/simulated-executions",
            json=simulation("success-operation-001", estimated_cost=1.75),
        )
        saved_task = client.get(f"/tasks/{task_id}")

    result = response.json()
    assert response.status_code == 201
    assert result["status"] == "completed"
    assert result["estimated_cost"] == 1.75
    assert result["simulated_changed_files"] == ["simulation/client-site/example-change.txt"]
    assert result["simulated_test_results"][0]["status"] == "passed"
    assert result["evidence"]["simulated"] is True
    assert result["started_at"] <= result["completed_at"]
    assert saved_task.json()["status"] == "completed"
    assert saved_task.json()["status"] != "verified"

    from app.database import SessionLocal
    from app import models

    with SessionLocal() as database:
        assert database.get(models.Finding, finding_id).status == "open"


def test_operation_key_prevents_duplicate_execution() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id, _, task_id = make_eligible_task(client, "Simulator Duplicate", ready=True)
        payload = simulation("duplicate-operation-001")
        first = client.post(f"/tasks/{task_id}/simulated-executions", json=payload)
        repeated = client.post(f"/tasks/{task_id}/simulated-executions", json=payload)
        saved = client.get(f"/clients/{client_id}/executions")

        _, _, other_task_id = make_eligible_task(client, "Simulator Other Client", ready=True)
        wrong_task = client.post(f"/tasks/{other_task_id}/simulated-executions", json=payload)

    assert repeated.json()["id"] == first.json()["id"]
    assert repeated.json()["reused_existing"] is True
    assert len(saved.json()) == 1
    assert wrong_task.status_code == 409
    assert "another task" in wrong_task.json()["detail"]


def test_retries_only_represent_temporary_failures_and_never_sleep() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        _, _, recovered_task = make_eligible_task(client, "Simulator Recovery", ready=True)
        recovered = client.post(
            f"/tasks/{recovered_task}/simulated-executions",
            json=simulation("retry-recovered-001", temporary_failures_before_result=2),
        )

        _, _, temporary_task = make_eligible_task(client, "Simulator Temporary Failure", ready=True)
        temporary = client.post(
            f"/tasks/{temporary_task}/simulated-executions",
            json=simulation("retry-temporary-001", "failure", "temporary"),
        )

        _, _, permanent_task = make_eligible_task(client, "Simulator Permanent Failure", ready=True)
        permanent = client.post(
            f"/tasks/{permanent_task}/simulated-executions",
            json=simulation("retry-permanent-001", "failure", "permanent"),
        )

    assert recovered.json()["attempt_count"] == 3
    assert recovered.json()["retry_delays_seconds"] == [10, 60]
    assert temporary.json()["attempt_count"] == 4
    assert temporary.json()["retry_delays_seconds"] == [10, 60, 300]
    assert permanent.json()["attempt_count"] == 1
    assert permanent.json()["retry_delays_seconds"] == []


def test_failed_and_blocked_outcomes_are_not_completed() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        _, _, failed_task = make_eligible_task(client, "Simulator Failed", ready=True)
        missing_type = client.post(
            f"/tasks/{failed_task}/simulated-executions",
            json=simulation("failure-missing-type", "failure"),
        )
        failed = client.post(
            f"/tasks/{failed_task}/simulated-executions",
            json=simulation("failure-permanent-002", "failure", "permanent"),
        )

        _, _, blocked_task = make_eligible_task(client, "Simulator Blocked", ready=True)
        blocked = client.post(
            f"/tasks/{blocked_task}/simulated-executions",
            json=simulation("blocked-operation-001", "blocked"),
        )

    assert missing_type.status_code == 422
    assert failed.json()["status"] == "failed"
    assert failed.json()["simulated_changed_files"] == []
    assert failed.json()["error_message"] == "Simulated permanent failure"
    assert blocked.json()["status"] == "blocked"
    assert blocked.json()["attempt_count"] == 1
    assert blocked.json()["retry_delays_seconds"] == []


def test_execution_lists_keep_client_records_separate_and_demo_page_is_visible() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        first_client, _, first_task = make_eligible_task(client, "First Execution Client", ready=True)
        second_client, _, second_task = make_eligible_task(client, "Second Execution Client", ready=True)
        first_execution = client.post(
            f"/tasks/{first_task}/simulated-executions",
            json=simulation("separation-first-001"),
        ).json()
        second_execution = client.post(
            f"/tasks/{second_task}/simulated-executions",
            json=simulation("separation-second-001", "blocked"),
        ).json()
        first_list = client.get(f"/clients/{first_client}/executions")
        second_list = client.get(f"/clients/{second_client}/executions")
        page = client.get("/dashboard/fulfillment")

    assert {item["id"] for item in first_list.json()} == {first_execution["id"]}
    assert {item["client_id"] for item in first_list.json()} == {first_client}
    assert {item["id"] for item in second_list.json()} == {second_execution["id"]}
    assert {item["client_id"] for item in second_list.json()} == {second_client}
    assert page.status_code == 200
    assert "Nothing here changes a real client system" in page.text
