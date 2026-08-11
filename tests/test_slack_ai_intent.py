"""Natural Slack wording is safely mapped onto existing allowlisted actions."""

from __future__ import annotations

from uuid import uuid4

from app import slack_conversation_service
from tests.test_slack import (
    FakeSlackAdapter,
    connect_fake_slack,
    create_client,
    post_signed_slack_event,
)


def _interpretation(command: str | None, confidence: float = 0.96):
    return slack_conversation_service.SlackActionInterpretation(
        canonical_command=command,
        confidence=confidence,
        model="gpt-test-intent",
        input_tokens=30,
        output_tokens=8,
        estimated_cost_usd=0.00001,
    )


def test_explicit_outcome_command_is_parsed_without_ai() -> None:
    from app.slack_action_service import detect_owner_action

    action = detect_owner_action(
        'record outcome for task task_1234abcd {"operation_key":"outcome:1","metric_name":"Organic clicks","assessment":"met","source_type":"live_api","source_reference":"Search Console","evidence":["export 1"],"notes":"Observed after 28 days","observed_at":"2026-08-22T12:00:00"}',
        has_mapped_client=True,
    )

    assert action is not None
    assert action.action_type == "record_outcome"
    assert action.task_id == "task_1234abcd"
    assert action.outcome_payload["assessment"] == "met"


def test_content_review_command_is_parsed_without_ai() -> None:
    from app.slack_action_service import detect_owner_action

    action = detect_owner_action(
        'approve content review packet packet_1234abcd {"checklist":{"facts_supported":true},"notes":"Reviewed"}',
        has_mapped_client=True,
    )

    assert action is not None
    assert action.action_type == "record_content_review"
    assert action.packet_id == "packet_1234abcd"
    assert action.content_review_payload["notes"] == "Reviewed"


def test_ai_intent_can_remove_a_mapped_client_from_natural_wording(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    captured: list[str] = []

    def interpret(question: str, *, has_mapped_client: bool):
        captured.append(question)
        assert has_mapped_client is True
        return _interpretation("delete this client")

    monkeypatch.setattr(slack_conversation_service, "interpret_action", interpret)
    with TestClient(app) as api:
        client_id = create_client(api, f"Natural Delete {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_natural_delete_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_CHANNEL_MEMBER",
                    "channel": connection["channel_id"],
                    "text": "<@U_BOT> take this shop off our roster",
                },
            },
        )
        saved = api.get(f"/clients/{client_id}").json()

    assert response.status_code == 200
    assert captured == ["take this shop off our roster"]
    assert saved["status"] == "archived"
    assert connection["channel_id"] in adapter.archived_channel_ids


def test_ai_intent_can_generate_client_report_from_natural_wording(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    monkeypatch.setattr(
        slack_conversation_service,
        "interpret_action",
        lambda _question, *, has_mapped_client: _interpretation(
            "simple report for this client"
        ),
    )
    with TestClient(app) as api:
        client_id = create_client(api, f"Natural Report {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_natural_report_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_CHANNEL_MEMBER",
                    "channel": connection["channel_id"],
                    "text": "<@U_BOT> pull together how things are looking for this shop",
                },
            },
        )

    assert response.status_code == 200
    assert "Simple saved-data update" in adapter.messages[-1]["text"]
    assert "Natural Report" in adapter.messages[-1]["text"]


def test_slack_can_record_a_source_backed_outcome_for_a_completed_task(monkeypatch) -> None:
    import json
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.test_tasks import approve, change, make_findings, proposal

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id, findings = make_findings(api, "Slack Outcome")
        task_id = api.post(f"/clients/{client_id}/tasks", json=proposal(findings[0]["id"])).json()["id"]
        approve(api, task_id)
        change(api, task_id, "ready")
        change(api, task_id, "running")
        change(api, task_id, "completed")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        payload = {
            "operation_key": f"outcome:slack:{task_id}",
            "metric_name": "Organic clicks",
            "baseline_value": 100,
            "observed_value": 125,
            "unit": "clicks / 28 days",
            "assessment": "met",
            "source_type": "live_api",
            "source_reference": "Search Console export sc-28d",
            "evidence": ["Export sc-28d shows 125 clicks", "Baseline was 100 clicks"],
            "notes": "Recorded after the verification window.",
            "observed_at": "2026-08-22T12:00:00",
        }
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_outcome_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_CHANNEL_MEMBER",
                    "channel": connection["channel_id"],
                    "text": f"<@U_BOT> record outcome for task {task_id} {json.dumps(payload)}",
                },
            },
        )
        saved = api.get(f"/tasks/{task_id}/outcomes")

    assert response.status_code == 200
    assert saved.status_code == 200
    assert len(saved.json()) == 1
    assert saved.json()[0]["assessment"] == "met"
    assert "recorded as `met`" in adapter.messages[-1]["text"]


def test_hypothetical_remove_question_does_not_execute(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    monkeypatch.setattr(
        slack_conversation_service,
        "interpret_action",
        lambda _question, *, has_mapped_client: _interpretation(None, 0.99),
    )
    monkeypatch.setattr(
        slack_conversation_service,
        "answer_question",
        lambda question, **_kwargs: slack_conversation_service.SlackConversationAnswer(
            text=f"Hypothetical answer: {question}",
            model="gpt-test",
            input_tokens=20,
            output_tokens=10,
            estimated_cost_usd=0.0001,
        ),
    )
    with TestClient(app) as api:
        client_id = create_client(api, f"Keep Hypothetical {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_hypothetical_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_CHANNEL_MEMBER",
                    "channel": connection["channel_id"],
                    "text": "<@U_BOT> what would happen if we remove this client?",
                },
            },
        )
        saved = api.get(f"/clients/{client_id}").json()

    assert response.status_code == 200
    assert saved["status"] == "onboarding"
    assert connection["channel_id"] not in adapter.archived_channel_ids
    assert "Hypothetical answer" in adapter.messages[-1]["text"]


def test_literal_parser_never_executes_negative_or_hypothetical_wording() -> None:
    from app.slack_action_service import detect_owner_action

    for wording in (
        "if we delete this client, what happens?",
        "don't delete this client",
        "I do not want you to remove this client",
        "hypothetically remove this client",
    ):
        assert detect_owner_action(wording, has_mapped_client=True) is None


def test_low_confidence_ai_action_does_not_execute_or_fall_through_to_q_and_a(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    monkeypatch.setattr(
        slack_conversation_service,
        "interpret_action",
        lambda _question, *, has_mapped_client: _interpretation("delete this client", 0.41),
    )
    monkeypatch.setattr(
        slack_conversation_service,
        "answer_question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("low-confidence intent reached Q&A")),
    )
    with TestClient(app) as api:
        client_id = create_client(api, f"Low Confidence Delete {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_low_confidence_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_CHANNEL_MEMBER",
                    "channel": connection["channel_id"],
                    "text": "<@U_BOT> maybe take this shop off our roster?",
                },
            },
        )
        saved = api.get(f"/clients/{client_id}").json()

    assert response.status_code == 200
    assert saved["status"] == "onboarding"
    assert connection["channel_id"] not in adapter.archived_channel_ids
    assert "did not change anything" in adapter.messages[-1]["text"]
