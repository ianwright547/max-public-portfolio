"""Phase 10 tests for execution verification and finding resolution."""

from tests.test_fulfillment import make_eligible_task, simulation


def make_completed_execution(client, label: str, operation_key: str) -> tuple[str, str, str, dict]:
    client_id, finding_id, task_id = make_eligible_task(client, label, ready=True)
    execution = client.post(
        f"/tasks/{task_id}/simulated-executions",
        json=simulation(operation_key),
    ).json()
    return client_id, finding_id, task_id, execution


def review_payload(
    decision_key: str,
    outcome: str = "verified",
    explanation: str = "The saved result matches the approved request.",
) -> dict:
    return {
        "decision_key": decision_key,
        "outcome": outcome,
        "reviewer": "Agency Owner",
        "explanation": explanation,
        "review_evidence": ["Compared the approved request with the execution record"],
        "correct_client_confirmed": True,
        "approved_task_followed": True,
        "output_exists": True,
        "result_matches_requested_outcome": True,
        "no_unexpected_changes": True,
    }


def test_successful_verification_resolves_finding_and_keeps_verification_distinct() -> None:
    from fastapi.testclient import TestClient

    from app import models
    from app.database import SessionLocal
    from app.main import app

    with TestClient(app) as client:
        client_id, finding_id, task_id, execution = make_completed_execution(
            client, "Verified Execution", "verify-success-execution"
        )
        response = client.post(
            f"/executions/{execution['id']}/verifications",
            json=review_payload("verify-success-decision"),
        )
        task = client.get(f"/tasks/{task_id}")

    assert response.status_code == 201
    assert response.json()["outcome"] == "verified"
    assert response.json()["client_id"] == client_id
    assert response.json()["validation_results"]["tests_passed"] is True
    assert response.json()["resolved_finding"] is True
    assert task.json()["status"] == "verified"

    with SessionLocal() as database:
        finding = database.get(models.Finding, finding_id)
        assert finding.status == "resolved"
        assert finding.resolved_at is not None


def test_missing_execution_evidence_cannot_be_verified() -> None:
    from fastapi.testclient import TestClient

    from app import models
    from app.database import SessionLocal
    from app.main import app

    with TestClient(app) as client:
        _, finding_id, task_id, execution = make_completed_execution(
            client, "Missing Verification Evidence", "missing-evidence-execution"
        )
        with SessionLocal() as database:
            saved = database.get(models.FulfillmentExecution, execution["id"])
            saved.evidence = {}
            database.commit()

        invalid_verified = client.post(
            f"/executions/{execution['id']}/verifications",
            json=review_payload("missing-evidence-invalid-verified"),
        )
        not_enough = client.post(
            f"/executions/{execution['id']}/verifications",
            json=review_payload(
                "missing-evidence-decision",
                "not_enough_evidence",
                "The execution record does not contain source evidence.",
            ),
        )
        task = client.get(f"/tasks/{task_id}")

    assert invalid_verified.status_code == 409
    assert "evidence_present" in invalid_verified.json()["detail"]
    assert not_enough.json()["outcome"] == "not_enough_evidence"
    assert not_enough.json()["validation_results"]["evidence_present"] is False
    assert task.json()["status"] == "completed"
    with SessionLocal() as database:
        assert database.get(models.Finding, finding_id).status == "open"


def test_missing_acceptance_contract_cannot_be_verified() -> None:
    from fastapi.testclient import TestClient

    from app import models
    from app.database import SessionLocal
    from app.main import app

    with TestClient(app) as client:
        _, finding_id, task_id, execution = make_completed_execution(
            client, "Missing Acceptance Contract", "missing-acceptance-contract-execution"
        )
        with SessionLocal() as database:
            task = database.get(models.Task, task_id)
            task.expected_result = ""
            task.success_metric = ""
            task.verification_window = ""
            database.commit()
        invalid_verified = client.post(
            f"/executions/{execution['id']}/verifications",
            json=review_payload("missing-acceptance-contract-invalid"),
        )

    assert invalid_verified.status_code == 409
    assert "acceptance_contract_present" in invalid_verified.json()["detail"]


def test_wrong_client_evidence_fails_verification_and_returns_task_for_correction() -> None:
    from fastapi.testclient import TestClient

    from app import models
    from app.database import SessionLocal
    from app.main import app

    with TestClient(app) as client:
        _, finding_id, task_id, execution = make_completed_execution(
            client, "Wrong Client Evidence", "wrong-client-execution"
        )
        other_client_id, _, _ = make_eligible_task(client, "Evidence From Other Client")
        with SessionLocal() as database:
            saved = database.get(models.FulfillmentExecution, execution["id"])
            saved.evidence = {**saved.evidence, "client_id": other_client_id}
            database.commit()

        response = client.post(
            f"/executions/{execution['id']}/verifications",
            json=review_payload(
                "wrong-client-decision",
                "verification_failed",
                "The evidence names a different client.",
            ),
        )
        task = client.get(f"/tasks/{task_id}")

    assert response.json()["outcome"] == "verification_failed"
    assert response.json()["validation_results"]["correct_client"] is False
    assert response.json()["client_id"] != other_client_id
    assert task.json()["status"] == "failed"
    with SessionLocal() as database:
        assert database.get(models.Finding, finding_id).status == "open"


def test_failed_execution_tests_cannot_be_presented_as_verified() -> None:
    from fastapi.testclient import TestClient

    from app import models
    from app.database import SessionLocal
    from app.main import app

    with TestClient(app) as client:
        _, finding_id, task_id, execution = make_completed_execution(
            client, "Failed Verification Tests", "failed-tests-execution"
        )
        with SessionLocal() as database:
            saved = database.get(models.FulfillmentExecution, execution["id"])
            saved.simulated_test_results = [
                {"name": "simulated task check", "status": "failed", "simulated": True}
            ]
            database.commit()

        response = client.post(
            f"/executions/{execution['id']}/verifications",
            json=review_payload(
                "failed-tests-decision",
                "verification_failed",
                "The recorded execution test failed.",
            ),
        )
        task = client.get(f"/tasks/{task_id}")

    assert response.json()["validation_results"]["tests_present"] is True
    assert response.json()["validation_results"]["tests_passed"] is False
    assert task.json()["status"] == "failed"
    with SessionLocal() as database:
        assert database.get(models.Finding, finding_id).status == "open"


def test_repeated_verification_reuses_decision_and_preserves_previous_reviews() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        _, _, _, execution = make_completed_execution(
            client, "Repeated Verification", "repeated-review-execution"
        )
        manual_payload = review_payload(
            "repeated-review-decision",
            "needs_manual_review",
            "A second reviewer should inspect the recorded file.",
        )
        first = client.post(
            f"/executions/{execution['id']}/verifications", json=manual_payload
        )
        repeated = client.post(
            f"/executions/{execution['id']}/verifications", json=manual_payload
        )
        verified = client.post(
            f"/executions/{execution['id']}/verifications",
            json=review_payload("repeated-review-final"),
        )
        history = client.get(f"/executions/{execution['id']}/verifications")

    assert repeated.json()["id"] == first.json()["id"]
    assert repeated.json()["reused_existing"] is True
    assert verified.json()["outcome"] == "verified"
    assert [item["outcome"] for item in history.json()] == [
        "needs_manual_review",
        "verified",
    ]


def test_human_review_screen_shows_request_actions_files_tests_evidence_and_history() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        _, _, _, execution = make_completed_execution(
            client, "Verification Review Screen", "review-screen-execution"
        )
        pending_page = client.get("/dashboard/verifications")
        client.post(
            f"/executions/{execution['id']}/verifications",
            json=review_payload(
                "review-screen-manual",
                "needs_manual_review",
                "Waiting for another reviewer.",
            ),
        )
        history_page = client.get("/dashboard/verifications")

    assert pending_page.status_code == 200
    assert "Approved request" in pending_page.text
    assert "Execution actions" in pending_page.text
    assert "Changed files" in pending_page.text
    assert "Test results" in pending_page.text
    assert "Execution evidence" in pending_page.text
    assert "Record verification decision" in pending_page.text
    assert "Waiting for another reviewer" in history_page.text
