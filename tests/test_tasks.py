"""Phase 7 tests for evidence-backed task proposals and approval."""

from tests.test_health_checks import add_calls, add_intake, make_health_client


def make_findings(client, label: str, include_decline: bool = False) -> tuple[str, list[dict]]:
    client_id = make_health_client(client, label)
    add_intake(client, client_id)
    add_calls(client, client_id, 100, 60 if include_decline else 105)
    check = client.post(
        f"/clients/{client_id}/health-checks",
        json={"website_status": "unavailable"},
    )
    return client_id, check.json()["findings"]


def proposal(finding_id: str, dependency_ids=None) -> dict:
    return {
        "source_finding_id": finding_id,
        "title": "Restore the client website",
        "requested_outcome": "The saved client domain loads successfully and returns a normal response.",
        "reason": "The health check contains evidence that the website was unavailable.",
        "estimated_effort": "30-60 minutes",
        "risk": "medium",
        "required_access": ["hosting account"],
        "dependency_ids": dependency_ids or [],
    }


def approve(client, task_id: str, name: str = "Agency Owner"):
    return client.post(
        f"/tasks/{task_id}/decision",
        json={"decision": "approved", "decision_maker": name},
    )


def change(client, task_id: str, target: str, reason=None):
    return client.post(
        f"/tasks/{task_id}/status",
        json={"target_status": target, "changed_by": "Test operator", "reason": reason},
    )


def test_allowed_lifecycle_keeps_approval_completion_and_verification_distinct() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id, findings = make_findings(client, "Lifecycle Tasks")
        created = client.post(f"/clients/{client_id}/tasks", json=proposal(findings[0]["id"]))
        task_id = created.json()["id"]
        approved = approve(client, task_id)
        ready = change(client, task_id, "ready")
        running = change(client, task_id, "running")
        completed = change(client, task_id, "completed")
        verified = change(client, task_id, "verified", "Loaded the domain and confirmed the expected page")

    assert created.json()["status"] == "proposed"
    assert approved.json()["status"] == "approved"
    assert ready.json()["status"] == "ready"
    assert running.json()["status"] == "running"
    assert completed.json()["status"] == "completed"
    assert completed.json()["status"] != "verified"
    assert verified.json()["status"] == "verified"
    assert approved.json()["approval_information"][0]["decision_maker"] == "Agency Owner"


def test_forbidden_transitions_and_terminal_states_are_rejected() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id, findings = make_findings(client, "Forbidden Tasks")
        task_id = client.post(f"/clients/{client_id}/tasks", json=proposal(findings[0]["id"])).json()["id"]
        skipped = change(client, task_id, "running")
        rejected = client.post(
            f"/tasks/{task_id}/decision",
            json={"decision": "rejected", "decision_maker": "Agency Owner", "reason": "Outside contract"},
        )
        revive = approve(client, task_id)

    assert skipped.status_code == 409
    assert "proposed to running" in skipped.json()["detail"]
    assert rejected.json()["status"] == "rejected"
    assert revive.status_code == 409


def test_rejection_requires_reason_and_does_not_change_task() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id, findings = make_findings(client, "Reject Tasks")
        task_id = client.post(f"/clients/{client_id}/tasks", json=proposal(findings[0]["id"])).json()["id"]
        response = client.post(
            f"/tasks/{task_id}/decision",
            json={"decision": "rejected", "decision_maker": "Agency Owner"},
        )
        saved = client.get(f"/tasks/{task_id}")

    assert response.status_code == 422
    assert response.json()["detail"] == "A rejection reason is required"
    assert saved.json()["status"] == "proposed"
    assert saved.json()["approval_information"] == []


def test_duplicate_active_task_for_same_finding_is_prevented() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id, findings = make_findings(client, "Duplicate Tasks")
        first = client.post(f"/clients/{client_id}/tasks", json=proposal(findings[0]["id"]))
        duplicate = client.post(f"/clients/{client_id}/tasks", json=proposal(findings[0]["id"]))

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert first.json()["id"] in duplicate.json()["detail"]


def test_dependencies_must_be_verified_before_task_becomes_ready() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id, findings = make_findings(client, "Dependency Tasks", include_decline=True)
        website = next(item for item in findings if item["title"] == "Website unavailable")
        decline = next(item for item in findings if item["title"] == "Calls declined")
        prerequisite_id = client.post(f"/clients/{client_id}/tasks", json=proposal(website["id"])).json()["id"]
        dependent_payload = proposal(decline["id"], [prerequisite_id])
        dependent_payload["title"] = "Investigate call decline"
        dependent_id = client.post(f"/clients/{client_id}/tasks", json=dependent_payload).json()["id"]
        approve(client, dependent_id)
        blocked_ready = change(client, dependent_id, "ready")

        approve(client, prerequisite_id)
        change(client, prerequisite_id, "ready")
        change(client, prerequisite_id, "running")
        change(client, prerequisite_id, "completed")
        change(client, prerequisite_id, "verified", "Website restoration independently verified")
        now_ready = change(client, dependent_id, "ready")

    assert blocked_ready.status_code == 409
    assert prerequisite_id in blocked_ready.json()["detail"]
    assert now_ready.json()["status"] == "ready"
    assert now_ready.json()["dependency_ids"] == [prerequisite_id]


def test_approval_and_status_history_are_preserved() -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app import models
    from app.database import SessionLocal
    from app.main import app

    with TestClient(app) as client:
        client_id, findings = make_findings(client, "Audit Tasks")
        task_id = client.post(f"/clients/{client_id}/tasks", json=proposal(findings[0]["id"])).json()["id"]
        approve(client, task_id, "Ian")
        change(client, task_id, "ready")

    with SessionLocal() as database:
        decisions = list(database.scalars(select(models.TaskDecision).where(models.TaskDecision.task_id == task_id)))
        events = list(
            database.scalars(
                select(models.TaskStatusEvent)
                .where(models.TaskStatusEvent.task_id == task_id)
                .order_by(models.TaskStatusEvent.changed_at, models.TaskStatusEvent.id)
            )
        )

    assert len(decisions) == 1
    assert decisions[0].decision == "approved"
    assert decisions[0].decision_maker == "Ian"
    assert [(event.from_status, event.to_status) for event in events] == [
        (None, "proposed"),
        ("proposed", "approved"),
        ("approved", "ready"),
    ]


def test_finding_dependencies_and_task_lists_cannot_cross_clients() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        first_id, first_findings = make_findings(client, "First Task Client")
        second_id, second_findings = make_findings(client, "Second Task Client")
        first_task = client.post(f"/clients/{first_id}/tasks", json=proposal(first_findings[0]["id"]))
        wrong_finding = client.post(f"/clients/{second_id}/tasks", json=proposal(first_findings[0]["id"]))
        cross_dependency = client.post(
            f"/clients/{second_id}/tasks",
            json=proposal(second_findings[0]["id"], [first_task.json()["id"]]),
        )
        first_list = client.get(f"/clients/{first_id}/tasks")
        second_list = client.get(f"/clients/{second_id}/tasks")

    assert wrong_finding.status_code == 409
    assert cross_dependency.status_code == 409
    assert {task["client_id"] for task in first_list.json()} == {first_id}
    assert second_list.json() == []


def test_pending_dashboard_shows_proposals_and_form_records_approval() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id, findings = make_findings(client, "Dashboard Approval")
        task_id = client.post(f"/clients/{client_id}/tasks", json=proposal(findings[0]["id"])).json()["id"]
        page = client.get("/dashboard/tasks/approvals")
        decision = client.post(
            f"/dashboard/tasks/{task_id}/decision",
            data={"decision": "approved", "decision_maker": "Ian"},
            follow_redirects=False,
        )
        after = client.get("/dashboard/tasks/approvals")

    assert page.status_code == 200
    assert task_id in page.text
    assert "Approval is permission—not completion" in page.text
    assert "Expected result" in page.text
    assert "Success metric" in page.text
    assert "Verification window" in page.text
    assert decision.status_code == 303
    assert task_id not in after.text


def test_outcome_measurement_is_durable_idempotent_and_returned_with_task() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id, findings = make_findings(client, "Outcome Measurement")
        task_id = client.post(f"/clients/{client_id}/tasks", json=proposal(findings[0]["id"])).json()["id"]
        approve(client, task_id)
        change(client, task_id, "ready")
        change(client, task_id, "running")
        change(client, task_id, "completed")
        payload = {
            "operation_key": f"outcome:{task_id}:2026-08",
            "metric_name": "Organic clicks",
            "baseline_value": 100,
            "observed_value": 128,
            "unit": "clicks / 28 days",
            "assessment": "met",
            "source_type": "live_api",
            "source_reference": "Search Console property example.com, 2026-08 export",
            "evidence": ["Search Console export ID sc_2026_08", "28-day clicks increased from 100 to 128"],
            "notes": "Observed after the task verification window.",
            "recorded_by": "Agency Owner",
            "observed_at": "2026-08-22T12:00:00",
        }
        first = client.post(f"/tasks/{task_id}/outcomes", json=payload)
        replay = client.post(f"/tasks/{task_id}/outcomes", json=payload)
        task = client.get(f"/tasks/{task_id}")
        listed = client.get(f"/tasks/{task_id}/outcomes")

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["reused_existing"] is True
    assert len(task.json()["outcome_measurements"]) == 1
    assert listed.json()[0]["assessment"] == "met"


def test_outcome_measurement_rejects_cross_client_execution_and_blank_evidence() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        first_id, first_findings = make_findings(client, "Outcome First")
        second_id, second_findings = make_findings(client, "Outcome Second")
        first_task = client.post(f"/clients/{first_id}/tasks", json=proposal(first_findings[0]["id"])).json()["id"]
        second_task = client.post(f"/clients/{second_id}/tasks", json=proposal(second_findings[0]["id"])).json()["id"]
        for task_id in (first_task, second_task):
            approve(client, task_id)
            change(client, task_id, "ready")
            change(client, task_id, "running")
            change(client, task_id, "completed")
        blank = client.post(
            f"/tasks/{first_task}/outcomes",
            json={
                "operation_key": "outcome:blank-evidence",
                "metric_name": "Calls",
                "assessment": "inconclusive",
                "source_type": "manual",
                "source_reference": "owner notes",
                "evidence": ["   "],
                "notes": "No evidence yet",
                "recorded_by": "Owner",
                "observed_at": "2026-08-22T12:00:00",
            },
        )
        cross = client.post(
            f"/tasks/{first_task}/outcomes",
            json={
                "operation_key": "outcome:cross-client",
                "execution_id": "missing-execution",
                "metric_name": "Calls",
                "assessment": "inconclusive",
                "source_type": "manual",
                "source_reference": "owner notes",
                "evidence": ["No verified source result"],
                "notes": "No result yet",
                "recorded_by": "Owner",
                "observed_at": "2026-08-22T12:00:00",
            },
        )

    assert blank.status_code == 422
    assert cross.status_code == 409
