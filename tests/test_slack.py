"""Slack tests use a fake adapter and never contact a real workspace."""

import hashlib
import hmac
import json
import time
from datetime import date
from uuid import uuid4

from sqlalchemy import select

from app import models, notification_service, slack_conversation_service, slack_service
from app.database import SessionLocal


class FakeSlackAdapter:
    def __init__(self, workspace_id: str = "T_MAX", fail_messages: bool = False) -> None:
        self.workspace = slack_service.SlackWorkspace(workspace_id, "Max Test Workspace", "U_BOT")
        self.channels: list[slack_service.SlackChannel] = []
        self.channel_states: dict[str, slack_service.SlackChannel] = {}
        self.messages: list[dict[str, str]] = []
        self.invites: list[tuple[str, list[str]]] = []
        self.archived_channel_ids: list[str] = []
        self.fail_messages = fail_messages

    def verify_workspace(self) -> slack_service.SlackWorkspace:
        return self.workspace

    def create_private_channel(self, channel_name: str) -> slack_service.SlackChannel:
        # Real Slack IDs are globally unique. Keep the fake realistic so tests
        # do not collide when the shared test database preserves prior rows.
        channel = slack_service.SlackChannel(f"C_FAKE_{uuid4().hex[:10]}", channel_name)
        self.channels.append(channel)
        self.channel_states[channel.id] = channel
        return channel

    def create_public_channel(self, channel_name: str) -> slack_service.SlackChannel:
        channel = slack_service.SlackChannel(f"C_FAKE_{uuid4().hex[:10]}", channel_name)
        self.channels.append(channel)
        self.channel_states[channel.id] = channel
        return channel

    def get_channel(self, channel_id: str) -> slack_service.SlackChannel:
        channel = self.channel_states.get(channel_id)
        if channel is None:
            raise slack_service.SlackIntegrationError("channel_not_found")
        return channel

    def invite_users(self, channel_id: str, user_ids: list[str]) -> None:
        self.invites.append((channel_id, user_ids))

    def archive_channel(self, channel_id: str) -> None:
        self.archived_channel_ids.append(channel_id)
        current = self.get_channel(channel_id)
        self.channel_states[channel_id] = slack_service.SlackChannel(
            current.id, current.name, is_archived=True
        )

    def post_message(
        self,
        channel_id: str,
        text: str,
        operation_key: str,
    ) -> slack_service.SlackMessage:
        if self.fail_messages:
            raise slack_service.SlackIntegrationError(
                "slack_temporarily_unavailable",
                retryable=True,
            )
        self.messages.append(
            {"channel_id": channel_id, "text": text, "operation_key": operation_key}
        )
        return slack_service.SlackMessage(channel_id, f"1700000000.{len(self.messages):06d}")


def create_client(api, business_name: str) -> str:
    response = api.post(
        "/clients",
        json={"business_name": business_name, "service_start_date": date.today().isoformat()},
    )
    assert response.status_code == 201
    return response.json()["id"]


def connect_fake_slack(monkeypatch, adapter: FakeSlackAdapter) -> None:
    monkeypatch.setenv("SLACK_WORKSPACE_ID", adapter.workspace.id)
    monkeypatch.setenv("SLACK_OWNER_USER_IDS", "U_OWNER")
    monkeypatch.setattr(slack_service, "get_slack_adapter", lambda: adapter)
    monkeypatch.setattr(
        slack_conversation_service,
        "answer_question",
        lambda question, *, client_context=None: slack_conversation_service.SlackConversationAnswer(
            text=f"Answer to: {question}",
            model="gpt-test",
            input_tokens=20,
            output_tokens=10,
            estimated_cost_usd=0.0001,
        ),
    )


def post_signed_slack_event(api, payload: dict, signing_secret: str = "event-secret"):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    signature = "v0=" + hmac.new(
        signing_secret.encode("utf-8"), base, hashlib.sha256
    ).hexdigest()
    return api.post(
        "/slack/events",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        },
    )


def test_slack_questions_retrieve_relevant_sop_excerpts() -> None:
    knowledge = slack_conversation_service.relevant_knowledge(
        "What approval is required before risky website publishing?"
    )

    titles = {item["title"] for item in knowledge}
    assert "Website Changes and Publishing" in titles
    assert sum(len(item["excerpt"]) for item in knowledge) <= 12_000
    assert all(item["path"].endswith(".md") for item in knowledge)


def test_slack_thread_context_is_bounded_and_scoped(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    channel = slack_service.SlackChannel("C_THREAD", "agency-thread")
    adapter.channel_states[channel.id] = channel
    captured: list[list[dict]] = []

    def answer(question: str, *, client_context=None, conversation_history=None):
        captured.append(conversation_history or [])
        return slack_conversation_service.SlackConversationAnswer(
            text=f"Answer to: {question}",
            model="gpt-test",
            input_tokens=20,
            output_tokens=10,
            estimated_cost_usd=0.0001,
        )

    monkeypatch.setattr(slack_conversation_service, "answer_question", answer)
    thread_ts = "1700000000.000001"
    with TestClient(app) as api:
        for index, text in enumerate(("first question", "follow up question"), start=1):
            response = post_signed_slack_event(
                api,
                {
                    "type": "event_callback",
                    "team_id": adapter.workspace.id,
                    "event_id": f"Ev_thread_{index}_{uuid4().hex}",
                    "event": {
                        "type": "app_mention",
                        "user": "U_OWNER",
                        "channel": channel.id,
                        "thread_ts": thread_ts,
                        "text": f"<@U_BOT> {text}",
                    },
                },
            )
            assert response.status_code == 200
        with SessionLocal() as database:
            turns = list(
                database.scalars(
                    select(models.SlackConversationTurn)
                    .where(models.SlackConversationTurn.channel_id == channel.id)
                    .order_by(models.SlackConversationTurn.created_at.asc())
                )
            )
    assert captured[0] == []
    assert captured[1][0]["question"] == "first question"
    assert len(turns) == 2
    assert all(turn.thread_ts == thread_ts for turn in turns)


def test_owner_can_control_max_from_a_direct_message(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_dm_{uuid4().hex}",
                "event": {
                    "type": "message",
                    "channel_type": "im",
                    "user": "U_OWNER",
                    "channel": "D_OWNER_MAX",
                    "ts": "1700000000.000010",
                    "text": "help",
                },
            },
        )
    assert response.status_code == 200
    assert response.json()["status"] == "responded_unmapped"
    assert "Slack controls available now" in adapter.messages[-1]["text"]


def test_owner_can_remove_an_explicitly_named_client_from_a_direct_message(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, f"DM Delete Client {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_dm_delete_{uuid4().hex}",
                "event": {
                    "type": "message",
                    "channel_type": "im",
                    "user": "U_OWNER",
                    "channel": "D_OWNER_MAX",
                    "ts": "1700000000.000011",
                    "text": f"remove {api.get(f'/clients/{client_id}').json()['business_name']} client",
                },
            },
        )
        saved = api.get(f"/clients/{client_id}").json()

    assert response.status_code == 200
    assert saved["status"] == "archived"
    assert connection["channel_id"] in adapter.archived_channel_ids
    assert "removed from active clients" in adapter.messages[-1]["text"]


def test_owner_dm_requests_a_client_reference_before_destructive_change(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_dm_delete_missing_{uuid4().hex}",
                "event": {
                    "type": "message",
                    "channel_type": "im",
                    "user": "U_OWNER",
                    "channel": "D_OWNER_MAX",
                    "ts": "1700000000.000012",
                    "text": "delete a client",
                },
            },
        )

    assert response.status_code == 200
    assert "Which client should I change?" in adapter.messages[-1]["text"]


def test_owner_dm_can_request_a_simple_update_for_all_clients(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    from app import client_update_service
    monkeypatch.setattr(client_update_service, "MAX_PORTFOLIO_CLIENTS", 10_000)
    with TestClient(app) as api:
        first_name = f"Portfolio Update One {uuid4().hex[:8]}"
        second_name = f"Portfolio Update Two {uuid4().hex[:8]}"
        create_client(api, first_name)
        create_client(api, second_name)
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_dm_portfolio_{uuid4().hex}",
                "event": {
                    "type": "message",
                    "channel_type": "im",
                    "user": "U_OWNER",
                    "channel": "D_OWNER_MAX",
                    "ts": "1700000000.000013",
                    "text": "give me a simple update on all clients",
                },
            },
        )

    assert response.status_code == 200
    assert first_name in adapter.messages[-1]["text"]
    assert second_name in adapter.messages[-1]["text"]


def test_non_owner_direct_message_is_not_processed(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_dm_unauth_{uuid4().hex}",
                "event": {
                    "type": "message",
                    "channel_type": "im",
                    "user": "U_OTHER",
                    "channel": "D_OTHER_MAX",
                    "ts": "1700000000.000011",
                    "text": "help",
                },
            },
        )
    assert response.status_code == 200
    assert response.json()["status"] == "unauthorized_dm"
    assert adapter.messages == []


def test_slack_action_exception_is_recorded_and_not_left_pending(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app import slack_action_service
    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    monkeypatch.setattr(
        slack_action_service,
        "apply_owner_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("forced action failure")),
    )
    payload = {
        "type": "event_callback",
        "team_id": adapter.workspace.id,
        "event_id": f"Ev_action_failure_{uuid4().hex}",
        "event": {
            "type": "app_mention",
            "user": "U_OWNER",
            "channel": "C_FAILURE",
            "text": "<@U_BOT> help",
        },
    }
    adapter.channel_states["C_FAILURE"] = slack_service.SlackChannel("C_FAILURE", "agency-failure")
    with TestClient(app) as api:
        first = post_signed_slack_event(api, payload)
        second = post_signed_slack_event(api, payload)
        with SessionLocal() as database:
            receipt = database.scalar(
                select(models.SlackActionReceipt).where(
                    models.SlackActionReceipt.action_key == f"event:{payload['event_id']}"
                )
            )
    assert first.status_code == 200
    assert first.json()["status"] == "responded_failed"
    assert second.json()["duplicate"] is True
    assert receipt.result_status == "responded_failed"
    assert "check Max" not in adapter.messages[-1]["text"]
    assert "admin" not in adapter.messages[-1]["text"].lower()
    assert "Retry the request in this conversation" in adapter.messages[-1]["text"]


def test_slack_action_failure_translates_approval_and_archive_errors() -> None:
    from fastapi import HTTPException
    from app.routes.slack import slack_action_failure_message

    archived = slack_action_failure_message(
        HTTPException(status_code=409, detail="archived_client"), "create_report"
    )
    browser = slack_action_failure_message(
        HTTPException(status_code=409, detail="browser_control_approval_required"), "run_browser_task"
    )
    billing = slack_action_failure_message(
        HTTPException(
            status_code=402,
            detail={
                "code": "billing_subscription_required",
                "message": "An active subscription is required before fulfillment can start.",
            },
        ),
        "publish_gbp_post",
    )

    assert "already archived" in archived
    assert "browser-control approval" in browser
    assert "active subscription is required" in billing
    assert "{" not in billing
    assert "admin" not in archived.casefold()


def test_slack_can_report_intake_and_onboarding_gaps(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, "Intake Status Client")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        intake = api.post(
            f"/clients/{client_id}/intakes",
            json={
                "phone_number": "555-0100",
                "email": "owner@example.com",
                "brand_colors": ["#111111"],
                "domain": "example.com",
                "business_hours": "Mon-Fri 9-5",
                "service_areas": ["Indianapolis"],
                "google_business_profile": "https://maps.google.com/example",
                "enabled_workflows": ["website"],
            },
        )
        assert intake.status_code == 201
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_intake_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": connection["channel_id"],
                    "text": "<@U_BOT> show intake status",
                },
            },
        )
    assert response.status_code == 200
    assert "Intake status" in adapter.messages[-1]["text"]
    assert "Client lifecycle" in adapter.messages[-1]["text"]


def test_slack_controls_gbp_post_approval_and_publish(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app import google_business_profile_service
    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")

    class Published:
        post_id = "locations/1/localPosts/99"

    monkeypatch.setattr(
        google_business_profile_service.GoogleBusinessProfileAdapter,
        "publish_post",
        lambda self, location_id, summary, call_to_action_url: Published(),
    )
    with TestClient(app) as api:
        client_id = create_client(api, "GBP Slack Client")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        api.post(
            f"/clients/{client_id}/google-business-profile",
            json={"account_id": "accounts/slack", "location_id": "locations/slack", "location_name": "GBP Slack Client"},
        )
        draft = api.post(
            f"/clients/{client_id}/google-business-profile/posts",
            json={"operation_key": f"gbp-slack-{uuid4().hex}", "summary": "A truthful GBP update."},
        ).json()
        for command in (f"approve GBP post {draft['id']}", f"publish GBP post {draft['id']}"):
            response = post_signed_slack_event(
                api,
                {
                    "type": "event_callback",
                    "team_id": adapter.workspace.id,
                    "event_id": f"Ev_gbp_{uuid4().hex}",
                    "event": {
                        "type": "app_mention",
                        "user": "U_OWNER",
                        "channel": connection["channel_id"],
                        "text": f"<@U_BOT> {command}",
                    },
                },
            )
            assert response.status_code == 200
    assert "published" in adapter.messages[-1]["text"]


def test_slack_gbp_publish_respects_paid_entitlement(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app import google_business_profile_service
    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    calls = {"count": 0}

    class Published:
        post_id = "locations/paid/localPosts/1"

    def publish(*_args, **_kwargs):
        calls["count"] += 1
        return Published()

    monkeypatch.setattr(google_business_profile_service.GoogleBusinessProfileAdapter, "publish_post", publish)
    with TestClient(app) as api:
        client_id = create_client(api, f"GBP Paid Slack {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        api.post(
            f"/clients/{client_id}/google-business-profile",
            json={"account_id": "accounts/paid", "location_id": "locations/paid", "location_name": "Paid GBP"},
        )
        draft = api.post(
            f"/clients/{client_id}/google-business-profile/posts",
            json={"operation_key": f"gbp-paid-{uuid4().hex}", "summary": "A truthful GBP update."},
        ).json()
        api.post(f"/google-business-profile/posts/{draft['id']}/approval", json={"approved_by": "Owner"})
        monkeypatch.setenv("MAX_BILLING_ENFORCEMENT", "true")
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_gbp_paid_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": connection["channel_id"],
                    "text": f"<@U_BOT> publish GBP post {draft['id']}",
                },
            },
        )

    assert response.status_code == 200
    assert calls["count"] == 0
    assert "active subscription is required" in adapter.messages[-1]["text"]
    assert "{" not in adapter.messages[-1]["text"]


def test_owner_can_create_gbp_post_draft_from_slack(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, f"GBP Draft Slack Client {uuid4().hex[:8]}")
        channel_id = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]["channel_id"]
        api.post(
            f"/clients/{client_id}/google-business-profile",
            json={
                "account_id": "accounts/slack-draft",
                "location_id": "locations/slack-draft",
                "location_name": "GBP Draft Slack Client",
            },
        )
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_gbp_draft_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": channel_id,
                    "text": (
                        '<@U_BOT> create GBP post '
                        '{"summary":"A truthful draft update.","call_to_action_url":"https://example.com/book"}'
                    ),
                },
            },
        )
        with SessionLocal() as database:
            post = database.scalar(
                select(models.GoogleBusinessProfilePost)
                .where(models.GoogleBusinessProfilePost.client_id == client_id)
                .order_by(models.GoogleBusinessProfilePost.created_at.desc())
            )

    assert response.status_code == 200
    assert post is not None
    assert post.status == "draft"
    assert post.summary == "A truthful draft update."
    assert "not published" in adapter.messages[-1]["text"]


def test_slack_controls_per_client_scheduled_workflows(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, "Workflow Slack Client")
        channel_id = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]["channel_id"]
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_workflow_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": channel_id,
                    "text": "<@U_BOT> enable health checks",
                },
            },
        )
        assert response.status_code == 200
        with SessionLocal() as database:
            job = database.scalar(
                select(models.ScheduledJob).where(
                    models.ScheduledJob.client_id == client_id,
                    models.ScheduledJob.job_type == "health_check",
                )
            )
    assert job is not None
    assert job.enabled is True


def test_slack_can_enable_an_in_depth_daily_plan_with_persisted_configuration(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, "In Depth Workflow Client")
        channel_id = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]["channel_id"]
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_daily_depth_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": channel_id,
                    "text": "<@U_BOT> enable in-depth daily plans",
                },
            },
        )
        with SessionLocal() as database:
            job = database.scalar(
                select(models.ScheduledJob).where(
                    models.ScheduledJob.client_id == client_id,
                    models.ScheduledJob.job_type == "daily_client_plan",
                )
            )

    assert response.status_code == 200
    assert job is not None
    assert job.enabled is True
    assert job.parameters == {
        "depth": "in_depth",
        "focus": "all",
        "create_report": False,
        "create_tasks": False,
        "report_type": "internal",
    }


def test_slack_can_submit_a_validated_immutable_intake(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, "Slack Intake Submit Client")
        channel_id = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]["channel_id"]
        payload = {
            "phone_number": "555-0111",
            "email": "owner@slack-intake.example",
            "brand_colors": ["#112233"],
            "domain": "slack-intake.example",
            "business_hours": "Mon-Fri 8-5",
            "service_areas": ["Indianapolis"],
            "google_business_profile": "https://maps.google.com/slack-intake",
            "enabled_workflows": ["health_checks"],
        }
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_intake_submit_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": channel_id,
                    "text": f"<@U_BOT> submit intake {json.dumps(payload)}",
                },
            },
        )
        assert response.status_code == 200
        with SessionLocal() as database:
            intake = database.scalar(select(models.Intake).where(models.Intake.client_id == client_id))
    assert intake is not None
    assert "saved immutably" in adapter.messages[-1]["text"]


def test_slack_can_connect_a_client_website_without_credentials(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, "Slack Connection Client")
        channel_id = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]["channel_id"]
        payload = {
            "external_project_id": "vercel-slack-1",
            "project_name": "slack-connection-site",
            "production_url": "https://slack-connection.example",
        }
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_connection_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": channel_id,
                    "text": f"<@U_BOT> connect website {json.dumps(payload)}",
                },
            },
        )
        assert response.status_code == 200
        saved = api.get(f"/clients/{client_id}/website-connection")
    assert saved.status_code == 200
    assert "connection" in adapter.messages[-1]["text"]


def test_slack_can_turn_a_numbered_daily_plan_item_into_an_approval_task(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app import client_update_service, daily_planning_service
    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, f"Slack Plan Task {uuid4().hex[:8]}")
        channel = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]["channel_id"]
        update = client_update_service.ClientUpdate(
            client_id=client_id,
            business_name="Slack Plan Task",
            mode="in_depth",
            status="onboarding",
            plan_30=["Fix the homepage title and verify Search Console click-through rate."],
            sources=["Fresh website audit"],
        )
        monkeypatch.setattr(
            daily_planning_service,
            "generate_portfolio_update",
            lambda _database, *, mode, client=None: client_update_service.PortfolioUpdate(mode=mode, clients=[update]),
        )
        plan_response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_plan_{uuid4().hex}",
                "event": {"type": "app_mention", "user": "U_CHANNEL_MEMBER", "channel": channel, "text": "<@U_BOT> in-depth daily plan for this client"},
            },
        )
        task_response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_plan_task_{uuid4().hex}",
                "event": {"type": "app_mention", "user": "U_CHANNEL_MEMBER", "channel": channel, "text": "<@U_BOT> make task from daily plan item 1"},
            },
        )
        tasks = api.get(f"/clients/{client_id}/tasks").json()

    assert plan_response.status_code == 200
    assert task_response.status_code == 200
    assert len(tasks) == 1
    assert tasks[0]["status"] == "proposed"
    assert "approval-required task" in adapter.messages[-1]["text"]


def test_slack_can_update_and_archive_the_mapped_client(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, "Slack Admin Client")
        channel_id = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]["channel_id"]
        for command in (
            'update client {"business_name":"Slack Admin Renamed"}',
            "archive this client",
        ):
            response = post_signed_slack_event(
                api,
                {
                    "type": "event_callback",
                    "team_id": adapter.workspace.id,
                    "event_id": f"Ev_admin_{uuid4().hex}",
                    "event": {
                        "type": "app_mention",
                        "user": "U_OWNER",
                        "channel": channel_id,
                        "text": f"<@U_BOT> {command}",
                    },
                },
            )
            assert response.status_code == 200
        saved = api.get(f"/clients/{client_id}").json()
    assert saved["business_name"] == "Slack Admin Renamed"
    assert saved["status"] == "archived"
    assert channel_id in adapter.archived_channel_ids


def test_cleared_channel_member_can_delete_client_and_its_slack_channel(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, f"Delete From Slack {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_delete_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_CHANNEL_MEMBER",
                    "channel": connection["channel_id"],
                    "text": "<@U_BOT> delete a cleint",
                },
            },
        )
        active_clients = api.get("/clients").json()
        saved = api.get(f"/clients/{client_id}").json()
        with SessionLocal() as database:
            saved_connection = database.scalar(
                select(models.SlackChannelConnection).where(
                    models.SlackChannelConnection.client_id == client_id
                )
            )

    assert response.status_code == 200
    assert all(item["id"] != client_id for item in active_clients)
    assert saved["status"] == "archived"
    assert saved["archived_at"] is not None
    assert saved_connection.connection_status == "archived"
    assert connection["channel_id"] in adapter.archived_channel_ids
    assert "removed from active clients" in adapter.messages[-1]["text"]


def test_direct_client_delete_archives_the_mapped_slack_channel(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    with TestClient(app) as api:
        client_id = create_client(api, f"Direct Delete {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        response = api.delete(f"/clients/{client_id}")

    assert response.status_code == 200
    assert connection["channel_id"] in adapter.archived_channel_ids


def test_slack_channel_archive_endpoint_retries_pending_cleanup(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app import models
    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    with TestClient(app) as api:
        client_id = create_client(api, f"Retry Channel Archive {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        with SessionLocal() as database:
            saved = database.scalar(
                select(models.SlackChannelConnection).where(
                    models.SlackChannelConnection.client_id == client_id
                )
            )
            saved.connection_status = "archive_pending"
            database.commit()
        response = api.post(f"/clients/{client_id}/slack-channel/archive")

    assert response.status_code == 200
    assert response.json()["connection_status"] == "archived"
    assert connection["channel_id"] in adapter.archived_channel_ids


def test_slack_can_record_metrics_and_create_a_report(monkeypatch) -> None:
    from datetime import date
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, "Slack Reporting Client")
        channel_id = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]["channel_id"]
        commands = (
            'record metric {"metric_name":"calls","value":42,"measurement_period":"2026-08","source_type":"manual"}',
            f'create report {{"report_type":"internal","period_start":"{date.today().isoformat()}","period_end":"{date.today().isoformat()}"}}',
        )
        for command in commands:
            response = post_signed_slack_event(
                api,
                {
                    "type": "event_callback",
                    "team_id": adapter.workspace.id,
                    "event_id": f"Ev_reporting_{uuid4().hex}",
                    "event": {
                        "type": "app_mention",
                        "user": "U_OWNER",
                        "channel": channel_id,
                        "text": f"<@U_BOT> {command}",
                    },
                },
            )
            assert response.status_code == 200
        reports = api.get(f"/clients/{client_id}/reports").json()
        metrics = api.get(f"/clients/{client_id}/metrics").json()
    assert len(reports) == 1
    assert reports[0]["status"] == "draft"
    assert any(item["metric_name"] == "calls" for item in metrics)


def test_slack_redacts_credentials_before_ai_and_audit(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    channel = slack_service.SlackChannel("C_REDACTION", "agency-redaction")
    adapter.channel_states[channel.id] = channel
    captured: dict = {}
    event_id = f"Ev_{uuid4().hex}"

    def answer(question: str, *, client_context=None):
        captured["question"] = question
        return slack_conversation_service.SlackConversationAnswer(
            text="The credential was removed.",
            model="gpt-test",
            input_tokens=10,
            output_tokens=5,
            estimated_cost_usd=0.0001,
        )

    monkeypatch.setattr(slack_conversation_service, "answer_question", answer)
    with TestClient(app) as api:
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": event_id,
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": channel.id,
                    "text": "<@U_BOT> check api_key=DEMO_SLACK_KEY",
                },
            },
        )
        with SessionLocal() as database:
            audit = database.scalar(
                select(models.AuditEvent).where(
                    models.AuditEvent.event_type == "slack_question_answered",
                    models.AuditEvent.record_id == event_id,
                )
            )

    assert response.status_code == 200
    assert captured["question"] == "check [REDACTED CREDENTIAL]"
    assert "DEMO_SLACK_KEY" not in json.dumps(audit.details)
    assert audit.details["question"] == captured["question"]


def test_slack_event_url_verification_requires_a_valid_signature(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        verified = post_signed_slack_event(
            api,
            {"type": "url_verification", "challenge": "max-challenge"},
        )
        rejected = api.post(
            "/slack/events",
            json={"type": "url_verification", "challenge": "forged"},
            headers={
                "X-Slack-Request-Timestamp": str(int(time.time())),
                "X-Slack-Signature": "v0=invalid",
            },
        )

    assert verified.status_code == 200
    assert verified.json() == {"challenge": "max-challenge"}
    assert rejected.status_code == 401
    assert rejected.json()["detail"] == "slack_signature_invalid"


def test_app_mention_replies_once_in_the_mapped_client_channel(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, "Mention Reply Client")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        payload = {
            "type": "event_callback",
            "team_id": adapter.workspace.id,
            "event_id": f"Ev_{uuid4().hex}",
            "event": {
                "type": "app_mention",
                "user": "U_OWNER",
                "channel": connection["channel_id"],
                "text": "<@U_BOT> this is a test say something",
            },
        }
        first = post_signed_slack_event(api, payload)
        duplicate = post_signed_slack_event(api, payload)

    assert first.status_code == 200
    assert first.json() == {"ok": True, "status": "responded", "duplicate": False}
    assert duplicate.json() == {"ok": True, "status": "responded", "duplicate": True}
    assert len(adapter.messages) == 1
    assert adapter.messages[0]["channel_id"] == connection["channel_id"]
    assert "Mention Reply Client" in adapter.messages[0]["text"]
    assert "Answer to: this is a test say something" in adapter.messages[0]["text"]


def test_reused_slack_event_id_with_different_payload_is_rejected(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, "Slack Replay Guard")
        channel_id = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]["channel_id"]
        payload = {
            "type": "event_callback",
            "team_id": adapter.workspace.id,
            "event_id": f"Ev_replay_{uuid4().hex}",
            "event": {
                "type": "app_mention",
                "user": "U_OWNER",
                "channel": channel_id,
                "text": "<@U_BOT> first payload",
            },
        }
        assert post_signed_slack_event(api, payload).status_code == 200
        payload["event"]["text"] = "<@U_BOT> altered payload"
        altered = post_signed_slack_event(api, payload)

    assert altered.status_code == 409
    assert altered.json()["detail"] == "slack_event_payload_mismatch"


def test_non_owner_app_mention_never_replies_in_an_unmapped_channel(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_NOT_OWNER",
                    "channel": "C_NOT_MAPPED",
                    "text": "<@U_BOT> hello",
                },
            },
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "status": "unmapped_channel"}
    assert adapter.messages == []


def test_app_mention_repairs_one_stale_archived_channel_mapping(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, "Stale Mapping Client")
        original = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        adapter.channel_states[original["channel_id"]] = slack_service.SlackChannel(
            original["channel_id"], f"archived-{original['channel_name']}", True
        )
        replacement = slack_service.SlackChannel("C_REPLACEMENT", original["channel_name"])
        adapter.channel_states[replacement.id] = replacement
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": replacement.id,
                    "text": "<@U_BOT> repair this mapping",
                },
            },
        )
        repaired = api.get(f"/clients/{client_id}/slack-channel")

    assert response.status_code == 200
    assert response.json()["status"] == "responded"
    assert repaired.json()["channel_id"] == replacement.id
    assert adapter.messages[-1]["channel_id"] == replacement.id


def test_owner_mention_adopts_one_exact_unmapped_client_channel(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    replacement = slack_service.SlackChannel("C_OWNER_ADOPT", "owner-adopt-client")
    adapter.channel_states[replacement.id] = replacement
    with TestClient(app) as api:
        client_id = create_client(api, "Owner Adopt Client")
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": replacement.id,
                    "text": "<@U_BOT> adopt this channel",
                },
            },
        )
        connected = api.get(f"/clients/{client_id}/slack-channel")

    assert response.status_code == 200
    assert response.json()["status"] == "responded"
    assert connected.json()["channel_id"] == replacement.id
    assert adapter.messages[-1]["channel_id"] == replacement.id


def test_non_owner_mention_cannot_adopt_an_unmapped_channel(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    channel = slack_service.SlackChannel("C_NO_ADOPT", "non-owner-client")
    adapter.channel_states[channel.id] = channel
    with TestClient(app) as api:
        client_id = create_client(api, "Non Owner Client")
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_NOT_OWNER",
                    "channel": channel.id,
                    "text": "<@U_BOT> adopt this channel",
                },
            },
        )
        connected = api.get(f"/clients/{client_id}/slack-channel")

    assert response.status_code == 200
    assert response.json()["status"] == "unmapped_channel"
    assert connected.status_code == 404
    assert adapter.messages == []


def test_owner_gets_a_safe_reply_in_a_real_unmapped_channel(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    channel = slack_service.SlackChannel("C_ORPHAN", "orphan-test-channel")
    adapter.channel_states[channel.id] = channel
    payload = {
        "type": "event_callback",
        "team_id": adapter.workspace.id,
        "event_id": f"Ev_{uuid4().hex}",
        "event": {
            "type": "app_mention",
            "user": "U_OWNER",
            "channel": channel.id,
            "text": "<@U_BOT> are you there",
        },
    }
    with TestClient(app) as api:
        first = post_signed_slack_event(api, payload)
        duplicate = post_signed_slack_event(api, payload)

    assert first.status_code == 200
    assert first.json()["status"] == "responded_unmapped"
    assert duplicate.json() == {
        "ok": True,
        "status": "responded_unmapped",
        "duplicate": True,
    }
    assert len(adapter.messages) == 1
    assert "Answer to: are you there" in adapter.messages[0]["text"]
    assert "not connected" not in adapter.messages[0]["text"]


def test_owner_in_unmapped_channel_receives_agency_record_context(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    channel = slack_service.SlackChannel("C_OWNER_AGENCY", "internal-owner-chat")
    adapter.channel_states[channel.id] = channel
    captured: dict = {}
    event_id = f"Ev_{uuid4().hex}"

    def answer(question: str, *, client_context=None):
        captured["question"] = question
        captured["context"] = client_context
        return slack_conversation_service.SlackConversationAnswer(
            text=f"You have {client_context['current_client_count']} current clients.",
            model="gpt-test",
            input_tokens=25,
            output_tokens=8,
            estimated_cost_usd=0.0001,
        )

    monkeypatch.setattr(slack_conversation_service, "answer_question", answer)
    with TestClient(app) as api:
        first_id = create_client(api, "Owner Agency One")
        second_id = create_client(api, "Owner Agency Two")
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": event_id,
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": channel.id,
                    "text": "<@U_BOT> how many clients do we have?",
                },
            },
        )
        with SessionLocal() as database:
            usage = database.scalar(
                select(models.AIUsageRecord).where(
                    models.AIUsageRecord.operation_key == f"slack:{event_id}"
                )
            )

    assert response.status_code == 200
    assert captured["question"] == "how many clients do we have?"
    assert captured["context"]["scope"] == "agency_owner"
    assert set(captured["context"]["ai_budget"]) == {
        "month",
        "budget_usd",
        "used_usd",
        "remaining_usd",
        "status",
    }
    assert captured["context"]["ai_budget"]["remaining_usd"] >= 0
    names = {item["business_name"] for item in captured["context"]["current_clients"]}
    assert {"Owner Agency One", "Owner Agency Two"}.issubset(names)
    assert first_id != second_id
    assert "You have" in adapter.messages[-1]["text"]
    assert usage.client_id is None
    assert usage.operation == "slack_agency_question_answer"


def test_owner_can_move_all_current_clients_past_onboarding_from_slack(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    channel = slack_service.SlackChannel("C_OWNER_ACTION", "all-agency-internal")
    adapter.channel_states[channel.id] = channel
    with TestClient(app) as api:
        first_id = create_client(api, "Slack Activate One")
        second_id = create_client(api, "Slack Activate Two")
        event_id = f"Ev_{uuid4().hex}"
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": event_id,
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": channel.id,
                    "text": (
                        "<@U_BOT> These are all current clients and they passed onboarding. "
                        "Can we move them past that phase?"
                    ),
                },
            },
        )
        with SessionLocal() as database:
            first = database.get(models.Client, first_id)
            second = database.get(models.Client, second_id)
            events = list(
                database.scalars(
                    select(models.AuditEvent).where(
                        models.AuditEvent.event_type == "slack_client_status_changed",
                        models.AuditEvent.details["slack_event_id"].as_string() == event_id,
                    )
                )
            )

    assert response.status_code == 200
    assert first.status == "active"
    assert second.status == "active"
    assert len(events) >= 2
    assert "moved" in adapter.messages[-1]["text"]
    assert "`active`" in adapter.messages[-1]["text"]


def test_mapped_channel_member_can_change_client_status_from_slack(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, "Protected Slack Status Client")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_NOT_OWNER",
                    "channel": connection["channel_id"],
                    "text": "<@U_BOT> mark this client active",
                },
            },
        )
        saved = api.get(f"/clients/{client_id}")

    assert response.status_code == 200
    assert saved.json()["status"] == "active"


def test_owner_must_name_client_before_slack_creates_a_record(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    channel = slack_service.SlackChannel("C_CREATE_CLIENT", "agency-operations")
    adapter.channel_states[channel.id] = channel
    event_id = f"Ev_{uuid4().hex}"
    with TestClient(app) as api:
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": event_id,
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": channel.id,
                    "text": "<@U_BOT> hey lets add a new client",
                },
            },
        )
        with SessionLocal() as database:
            created = database.scalar(
                select(models.Client).where(models.Client.business_name == f"New Client {event_id[-8:]}")
            )

    assert response.status_code == 200
    assert created is None
    assert "Which business" in adapter.messages[-1]["text"]


def test_owner_can_create_named_active_client_from_slack(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    channel = slack_service.SlackChannel("C_CREATE_NAMED", "agency-operations")
    adapter.channel_states[channel.id] = channel
    with TestClient(app) as api:
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": channel.id,
                    "text": (
                        "<@U_BOT> create a new client called Slack Auto Shop "
                        "starting 2026-08-01; they already passed onboarding"
                    ),
                },
            },
        )
        with SessionLocal() as database:
            created = database.scalar(
                select(models.Client).where(models.Client.business_name == "Slack Auto Shop")
            )

    assert response.status_code == 200
    assert created.service_start_date.isoformat() == "2026-08-01"
    assert created.status == "active"
    assert any(channel.name == "slack-auto-shop" for channel in adapter.channels)
    assert "Working channel: `#slack-auto-shop`" in adapter.messages[-1]["text"]


def test_owner_can_propose_and_approve_client_task_from_slack(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, f"Slack Task Client {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        proposed = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": connection["channel_id"],
                    "text": "<@U_BOT> create a task to fix the broken booking link low risk",
                },
            },
        )
        with SessionLocal() as database:
            task = database.scalar(
                select(models.Task)
                .where(models.Task.client_id == client_id)
                .order_by(models.Task.proposed_at.desc())
            )
            finding = database.get(models.Finding, task.source_finding_id)
            task_id = task.id
        approved = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": connection["channel_id"],
                    "text": "<@U_BOT> approve this",
                },
            },
        )
        with SessionLocal() as database:
            task = database.get(models.Task, task_id)
            decision = database.scalar(
                select(models.TaskDecision).where(models.TaskDecision.task_id == task_id)
            )
            audits = list(
                database.scalars(
                    select(models.AuditEvent).where(
                        models.AuditEvent.record_type == "task",
                        models.AuditEvent.record_id == task_id,
                    )
                )
            )

    assert proposed.status_code == 200
    assert approved.status_code == 200
    assert finding.source == "slack_owner_request"
    assert finding.evidence["slack_user_id"] == "U_OWNER"
    assert task.risk == "low"
    assert task.status == "approved"
    assert decision.decision_maker == "Slack owner U_OWNER"
    assert {event.event_type for event in audits} == {"slack_task_proposed", "slack_task_decided"}
    assert "No external work has started" in " ".join(message["text"] for message in adapter.messages)


def test_owner_can_request_website_generation_from_slack(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_profile_approval import make_proposal

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id, proposal = make_proposal(api, f"Slack Website Request {uuid4().hex[:8]}")
        approved = api.post(
            f"/profile-versions/{proposal['version_id']}/decision",
            json={"decision": "approve", "decision_maker": "Agency Owner"},
        )
        channel_id = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]["channel_id"]
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_website_request_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": channel_id,
                    "text": "<@U_BOT> request website generation as replicate",
                },
            },
        )
        with SessionLocal() as database:
            task = database.scalar(
                select(models.Task)
                .where(models.Task.client_id == client_id)
                .order_by(models.Task.proposed_at.desc())
            )
            audit = database.scalar(
                select(models.AuditEvent).where(
                    models.AuditEvent.event_type == "slack_website_generation_requested",
                    models.AuditEvent.record_id == task.id,
                )
            )

    assert approved.status_code == 200
    assert response.status_code == 200
    assert task.status == "proposed"
    assert task.risk == "high"
    assert audit.details["mode"] == "replicate"
    assert "approve task" in adapter.messages[-1]["text"]


def test_owner_can_retry_failed_task_from_slack(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_codex_work_packets import approved_task

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id, task_id = approved_task(api, f"Slack Retry Task {uuid4().hex[:8]}")
        channel_id = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]["channel_id"]
        with SessionLocal() as database:
            task = database.get(models.Task, task_id)
            task.status = "failed"
            database.commit()
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_task_retry_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": channel_id,
                    "text": f"<@U_BOT> retry task {task_id}",
                },
            },
        )
        with SessionLocal() as database:
            task = database.get(models.Task, task_id)
            audit = database.scalar(
                select(models.AuditEvent).where(
                    models.AuditEvent.event_type == "slack_task_status_changed",
                    models.AuditEvent.record_id == task_id,
                )
            )

    assert response.status_code == 200
    assert task.status == "ready"
    assert audit.details["previous_status"] == "failed"
    assert audit.details["new_status"] == "ready"
    assert "No external work was started" in adapter.messages[-1]["text"]


def test_slack_task_rejection_requires_a_reason(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, f"Slack Reject Client {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": connection["channel_id"],
                    "text": "<@U_BOT> create a task to replace all website content high risk",
                },
            },
        )
        with SessionLocal() as database:
            task = database.scalar(
                select(models.Task)
                .where(models.Task.client_id == client_id)
                .order_by(models.Task.proposed_at.desc())
            )
            task_id = task.id
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": connection["channel_id"],
                    "text": f"<@U_BOT> reject task {task_id}",
                },
            },
        )
        with SessionLocal() as database:
            task = database.get(models.Task, task_id)

    assert response.status_code == 200
    assert task.status == "proposed"
    assert "rejection reason is required" in adapter.messages[-1]["text"]


def test_owner_can_queue_onboarding_from_client_slack_channel(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_intakes import make_intake_payload

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, f"Slack Onboarding Client {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        intake = api.post(f"/clients/{client_id}/intakes", json=make_intake_payload())
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": connection["channel_id"],
                    "text": "<@U_BOT> start onboarding",
                },
            },
        )
        with SessionLocal() as database:
            run = database.scalar(
                select(models.OnboardingAutomationRun)
                .where(models.OnboardingAutomationRun.client_id == client_id)
                .order_by(models.OnboardingAutomationRun.created_at.desc())
            )
            audit = database.scalar(
                select(models.AuditEvent).where(
                    models.AuditEvent.event_type == "slack_onboarding_queued",
                    models.AuditEvent.record_id == run.id,
                )
            )

    assert intake.status_code == 201
    assert response.status_code == 200
    assert run.status == "queued"
    assert audit.details["reused"] is True
    assert "Onboarding run" in adapter.messages[-1]["text"]


def test_owner_can_approve_and_deliver_report_from_slack(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    today = date.today().isoformat()
    with TestClient(app) as api:
        client_id = create_client(api, f"Slack Report Client {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        report = api.post(
            f"/clients/{client_id}/reports",
            json={
                "report_type": "client",
                "period_start": today,
                "period_end": today,
                "generated_by": "Slack test",
            },
        ).json()
        approved = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": connection["channel_id"],
                    "text": f"<@U_BOT> approve report {report['id']}",
                },
            },
        )
        delivered = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": connection["channel_id"],
                    "text": f"<@U_BOT> send report {report['id']}",
                },
            },
        )
        with SessionLocal() as database:
            saved_report = database.get(models.Report, report["id"])
            delivery = database.scalar(
                select(models.ReportDelivery).where(models.ReportDelivery.report_id == report["id"])
            )

    assert approved.status_code == 200
    assert delivered.status_code == 200
    assert saved_report.status == "approved"
    assert saved_report.approved_by == "Slack owner U_OWNER"
    assert delivery.status == "delivered"
    assert delivery.channel_id == connection["channel_id"]
    assert any("delivery status: `delivered`" in message["text"] for message in adapter.messages)


def test_owner_can_approve_pending_profile_from_slack(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_profile_approval import make_proposal

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id, proposal = make_proposal(api, f"Slack Profile {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": connection["channel_id"],
                    "text": f"<@U_BOT> approve profile {proposal['version_id']}",
                },
            },
        )
        with SessionLocal() as database:
            version = database.get(models.ProfileVersion, proposal["version_id"])
            official = database.scalar(
                select(models.OfficialProfile).where(models.OfficialProfile.client_id == client_id)
            )
            audit = database.scalar(
                select(models.AuditEvent).where(
                    models.AuditEvent.event_type == "slack_profile_decided",
                    models.AuditEvent.record_id == proposal["version_id"],
                )
            )

    assert response.status_code == 200
    assert version.status == "approved"
    assert official.approved_version_id == proposal["version_id"]
    assert official.approved_by == "Slack owner U_OWNER"
    assert audit.details["decision"] == "approve"
    assert "was `approved`" in adapter.messages[-1]["text"]


def test_owner_can_correct_rejected_profile_from_slack(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_profile_approval import make_proposal

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id, proposal = make_proposal(api, f"Slack Profile Correction {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        rejected = api.post(
            f"/profile-versions/{proposal['version_id']}/decision",
            json={
                "decision": "reject",
                "decision_maker": "Agency Owner",
                "reason": "Phone needs correction",
            },
        )
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": connection["channel_id"],
                    "text": (
                        f"<@U_BOT> correct profile {proposal['version_id']} with "
                        '{"contact_information":{"phone":"555-0100"}}'
                    ),
                },
            },
        )
        with SessionLocal() as database:
            versions = list(
                database.scalars(
                    select(models.ProfileVersion)
                    .where(models.ProfileVersion.client_id == client_id)
                    .order_by(models.ProfileVersion.version_number.asc())
                )
            )

    assert rejected.status_code == 200
    assert response.status_code == 200
    assert len(versions) == 2
    assert versions[0].status == "rejected"
    assert versions[1].status == "pending"
    assert versions[1].profile_data["contact_information"]["phone"] == "555-0100"
    assert "new pending version" in adapter.messages[-1]["text"]


def test_owner_can_reject_connection_candidate_from_slack(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_intakes import make_intake_payload

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, f"Slack Candidate Client {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        api.post(f"/clients/{client_id}/intakes", json=make_intake_payload())
        with SessionLocal() as database:
            run = database.scalar(
                select(models.OnboardingAutomationRun).where(
                    models.OnboardingAutomationRun.client_id == client_id
                )
            )
            run.status = "awaiting_connection_review"
            candidate = models.ConnectionCandidate(
                run_id=run.id,
                client_id=client_id,
                provider="github",
                external_identifier="agency/wrong-repo",
                display_name="agency/wrong-repo",
                connection_data={"owner": "agency", "repository_name": "wrong-repo"},
                match_evidence={"reason": "ambiguous"},
                match_kind="uncertain",
                status="pending",
            )
            database.add(candidate)
            database.commit()
            candidate_id = candidate.id
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": connection["channel_id"],
                    "text": (
                        f"<@U_BOT> reject connection candidate {candidate_id} "
                        "because it belongs to another client"
                    ),
                },
            },
        )
        with SessionLocal() as database:
            candidate = database.get(models.ConnectionCandidate, candidate_id)
            run = database.get(models.OnboardingAutomationRun, candidate.run_id)
            audit = database.scalar(
                select(models.AuditEvent).where(
                    models.AuditEvent.event_type == "slack_connection_candidate_decided",
                    models.AuditEvent.record_id == candidate_id,
                )
            )

    assert response.status_code == 200
    assert candidate.status == "rejected"
    assert candidate.decided_by == "Slack owner U_OWNER"
    assert run.status == "blocked"
    assert audit.details["reason"] == "it belongs to another client"
    assert "was `rejected`" in adapter.messages[-1]["text"]


def test_owner_can_prepare_run_review_and_verify_website_task_from_slack(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes import website_execution, website_generation
    from tests.test_codex_work_packets import approved_task, link_repository, link_website

    monkeypatch.setattr(website_execution, "require_provider_health", lambda *args, **kwargs: {})

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    monkeypatch.setattr(
        website_generation,
        "generate_files",
        lambda *_args, **_kwargs: (
            [{"path": "app/page.tsx", "content": "export default function Page() {}"}],
            "prompt-artifact-slack",
        ),
    )
    monkeypatch.setattr(
        website_execution,
        "commit_website_files",
        lambda **_kwargs: {
            "branch": "main",
            "changed_paths": ["app/page.tsx"],
            "commit_shas": ["sha-slack"],
        },
    )
    with TestClient(app) as api:
        client_id, task_id = approved_task(api, f"Slack Website {uuid4().hex[:8]}")
        link_website(api, client_id, f"slack-website-{uuid4().hex[:8]}")
        link_repository(api, client_id, f"slack-website-{uuid4().hex[:8]}")
        # Packet creation intentionally verifies that the independently saved
        # website and repository connections belong to the same client.
        with SessionLocal() as database:
            website = database.scalar(
                select(models.WebsiteConnection).where(models.WebsiteConnection.client_id == client_id)
            )
            repository = database.scalar(
                select(models.GitHubRepositoryConnection).where(
                    models.GitHubRepositoryConnection.client_id == client_id
                )
            )
            repository.repository_name = website.project_name
            repository.repository_url = f"https://github.com/{repository.owner}/{website.project_name}"
            database.commit()
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]

        def mention(text: str):
            return post_signed_slack_event(
                api,
                {
                    "type": "event_callback",
                    "team_id": adapter.workspace.id,
                    "event_id": f"Ev_{uuid4().hex}",
                    "event": {
                        "type": "app_mention",
                        "user": "U_OWNER",
                        "channel": connection["channel_id"],
                        "text": f"<@U_BOT> {text}",
                    },
                },
            )

        prepared = mention(f"prepare website task {task_id} as improve")
        with SessionLocal() as database:
            packet = database.scalar(
                select(models.CodexWorkPacket)
                .where(models.CodexWorkPacket.task_id == task_id)
                .order_by(models.CodexWorkPacket.created_at.desc())
            )
            packet_id = packet.id
        executed = mention(f"run website task {task_id} using packet {packet_id}")
        with SessionLocal() as database:
            execution = database.scalar(
                select(models.FulfillmentExecution).where(
                    models.FulfillmentExecution.task_id == task_id
                )
            )
            execution_id = execution.id
        reviewed = mention(f"review execution {execution_id}")
        verified = mention(f"confirm verify execution {execution_id}")
        with SessionLocal() as database:
            task = database.get(models.Task, task_id)
            finding = database.get(models.Finding, task.source_finding_id)
            execution = database.get(models.FulfillmentExecution, execution_id)
            decision = database.scalar(
                select(models.ExecutionVerification).where(
                    models.ExecutionVerification.execution_id == execution_id
                )
            )

    assert prepared.status_code == 200
    assert executed.status_code == 200
    assert reviewed.status_code == 200
    assert verified.status_code == 200
    assert execution.evidence["task_id"] == task_id
    assert execution.evidence["client_id"] == client_id
    assert task.status == "verified"
    assert finding.status == "resolved"
    assert decision.outcome == "verified"
    assert "is verified" in adapter.messages[-1]["text"]


def test_owner_can_prepare_content_codex_packet_from_slack(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_codex_work_packets import approved_task, link_repository, link_website

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id, task_id = approved_task(api, f"Slack Content {uuid4().hex[:8]}")
        link_website(api, client_id, f"slack-content-{uuid4().hex[:8]}")
        link_repository(api, client_id, f"slack-content-{uuid4().hex[:8]}")
        with SessionLocal() as database:
            website = database.scalar(select(models.WebsiteConnection).where(models.WebsiteConnection.client_id == client_id))
            repository = database.scalar(select(models.GitHubRepositoryConnection).where(models.GitHubRepositoryConnection.client_id == client_id))
            repository.repository_name = website.project_name
            repository.repository_url = f"https://github.com/{repository.owner}/{website.project_name}"
            database.commit()
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": connection["channel_id"],
                    "text": f"<@U_BOT> prepare content task {task_id} as blog",
                },
            },
        )
        with SessionLocal() as database:
            packet_id = database.scalar(
                select(models.CodexWorkPacket.id).where(models.CodexWorkPacket.task_id == task_id)
            )
        blocked_generator = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": connection["channel_id"],
                    "text": f"<@U_BOT> run website task {task_id} using packet {packet_id}",
                },
            },
        )
        with SessionLocal() as database:
            packet = database.scalar(select(models.CodexWorkPacket).where(models.CodexWorkPacket.task_id == task_id))

    assert response.status_code == 200
    assert blocked_generator.status_code == 200
    assert "content packet" in adapter.messages[-1]["text"]
    assert packet.packet_data["local_seo_work_type"] == "blog"
    assert packet.packet_data["content_brief"]["content_type"] == "blog"


def test_owner_can_run_poll_review_and_verify_browser_task_from_slack(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes import browser_execution
    from tests.test_browser_execution import FakeWorker
    from tests.test_codex_work_packets import approved_task

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    monkeypatch.setattr(browser_execution, "BrowserWorkerAdapter", FakeWorker)
    with TestClient(app) as api:
        client_id, task_id = approved_task(api, f"Slack Browser {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]

        def mention(text: str):
            return post_signed_slack_event(
                api,
                {
                    "type": "event_callback",
                    "team_id": adapter.workspace.id,
                    "event_id": f"Ev_{uuid4().hex}",
                    "event": {
                        "type": "app_mention",
                        "user": "U_OWNER",
                        "channel": connection["channel_id"],
                        "text": f"<@U_BOT> {text}",
                    },
                },
            )

        submitted = mention(
            f"run browser task {task_id} at https://example.com to inspect the approved page"
        )
        with SessionLocal() as database:
            execution = database.scalar(
                select(models.FulfillmentExecution).where(
                    models.FulfillmentExecution.task_id == task_id
                )
            )
            execution_id = execution.id
        polled = mention(f"poll execution {execution_id}")
        reviewed = mention(f"review execution {execution_id}")
        verified = mention(f"confirm verify execution {execution_id}")
        with SessionLocal() as database:
            task = database.get(models.Task, task_id)
            execution = database.get(models.FulfillmentExecution, execution_id)
            decision = database.scalar(
                select(models.ExecutionVerification).where(
                    models.ExecutionVerification.execution_id == execution_id
                )
            )

    assert submitted.status_code == 200
    assert polled.status_code == 200
    assert reviewed.status_code == 200
    assert verified.status_code == 200
    assert execution.status == "completed"
    assert execution.simulated_test_results[0]["status"] == "passed"
    assert task.status == "verified"
    assert decision.outcome == "verified"


def test_owner_can_run_health_check_and_control_notification_from_client_slack(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.notification_service import NotificationEvent, deliver_notification

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, f"Slack Operations Client {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]

        def mention(text: str):
            return post_signed_slack_event(
                api,
                {
                    "type": "event_callback",
                    "team_id": adapter.workspace.id,
                    "event_id": f"Ev_{uuid4().hex}",
                    "event": {
                        "type": "app_mention",
                        "user": "U_OWNER",
                        "channel": connection["channel_id"],
                        "text": f"<@U_BOT> {text}",
                    },
                },
            )

        health = mention("run health check website available")
        with SessionLocal() as database:
            notification, _ = deliver_notification(
                database,
                NotificationEvent(
                    event_key=f"slack-ops-{uuid4().hex}",
                    client_id=client_id,
                    category="approval_required",
                    importance="medium",
                    explanation="Review this test notification.",
                    requested_action="Mark it read from Slack.",
                    related_record_type="task",
                    related_record_id="task_test_notification",
                ),
            )
            database.commit()
            notification_id = notification.id
        marked = mention(f"mark notification {notification_id} read")
        retried = mention(f"retry notification {notification_id}")
        missing_search_console = mention("sync search console")
        with SessionLocal() as database:
            check = database.scalar(
                select(models.HealthCheck)
                .where(models.HealthCheck.client_id == client_id)
                .order_by(models.HealthCheck.checked_at.desc())
            )
            notification = database.get(models.Notification, notification_id)
            delivery = database.scalar(
                select(models.SlackDelivery).where(
                    models.SlackDelivery.notification_id == notification_id
                )
            )

    assert health.status_code == 200
    assert marked.status_code == 200
    assert retried.status_code == 200
    assert missing_search_console.status_code == 200
    assert check.website_status == "available"
    assert notification.is_read is True
    assert delivery.status == "delivered"
    assert any("Search Console sync failed" in message["text"] for message in adapter.messages)


def test_owner_can_sync_portfolio_metrics_and_run_due_jobs_from_agency_slack(monkeypatch) -> None:
    from datetime import datetime, timedelta
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes import website_metrics

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    monkeypatch.setattr(
        website_metrics,
        "sync_website_metrics",
        lambda _database, _days: ([], ["unmatched.example"], True),
    )
    agency_channel = slack_service.SlackChannel("C_AGENCY_OPERATIONS", "all-agency-operations")
    adapter.channel_states[agency_channel.id] = agency_channel
    with TestClient(app) as api:
        client_id = create_client(api, f"Slack Due Job Client {uuid4().hex[:8]}")
        job = api.post(
            "/jobs",
            json={
                "job_key": f"slack-due-{uuid4().hex}",
                "job_type": "health_check",
                "client_id": client_id,
                "interval_minutes": 1440,
                "next_run_at": (datetime.utcnow() - timedelta(minutes=1)).isoformat(),
            },
        ).json()

        def mention(text: str):
            return post_signed_slack_event(
                api,
                {
                    "type": "event_callback",
                    "team_id": adapter.workspace.id,
                    "event_id": f"Ev_{uuid4().hex}",
                    "event": {
                        "type": "app_mention",
                        "user": "U_OWNER",
                        "channel": agency_channel.id,
                        "text": f"<@U_BOT> {text}",
                    },
                },
            )

        metrics = mention("sync website metrics for 30 days")
        due = mention("run due jobs")
        with SessionLocal() as database:
            saved_job = database.get(models.ScheduledJob, job["id"])
            metric_audit = database.scalar(
                select(models.AuditEvent).where(
                    models.AuditEvent.event_type == "slack_website_metrics_synced"
                )
            )
            due_audit = database.scalar(
                select(models.AuditEvent)
                .where(models.AuditEvent.event_type == "slack_due_jobs_run")
                .order_by(models.AuditEvent.created_at.desc())
            )

    assert metrics.status_code == 200
    assert due.status_code == 200
    assert saved_job.last_status == "completed"
    assert metric_audit.details["unmatched_count"] == 1
    assert due_audit.details["run_count"] >= 1
    assert any("due jobs" in message["text"] for message in adapter.messages)


def test_mapped_mention_only_passes_that_clients_verified_context(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    captured: dict = {}

    def answer(question: str, *, client_context=None):
        captured["question"] = question
        captured["context"] = client_context
        return slack_conversation_service.SlackConversationAnswer(
            text="Use the verified client facts.",
            model="gpt-test",
            input_tokens=25,
            output_tokens=8,
            estimated_cost_usd=0.0001,
        )

    monkeypatch.setattr(slack_conversation_service, "answer_question", answer)
    with TestClient(app) as api:
        client_id = create_client(api, "Context Safe Client")
        create_client(api, "Other Private Client")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": connection["channel_id"],
                    "text": "<@U_BOT> what do you know about this client?",
                },
            },
        )

    assert response.status_code == 200
    assert captured["question"] == "what do you know about this client?"
    assert captured["context"]["business_name"] == "Context Safe Client"
    assert "Other Private Client" not in json.dumps(captured["context"])


def test_create_and_reuse_one_public_channel_per_client(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    with TestClient(app) as api:
        client_id = create_client(api, "Slack Channel Client")
        first = api.post(f"/clients/{client_id}/slack-channel")
        second = api.post(f"/clients/{client_id}/slack-channel")
        saved = api.get(f"/clients/{client_id}/slack-channel")
        dashboard = api.get("/dashboard/slack")

    assert first.status_code == 200
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert saved.json()["client_id"] == client_id
    assert saved.json()["channel_id"] == adapter.channels[0].id
    assert saved.json()["connection_status"] == "connected_public"
    assert len(adapter.channels) == 1
    assert dashboard.status_code == 200
    assert "Slack Channel Client" in dashboard.text


def test_workspace_mismatch_stops_before_channel_creation(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter(workspace_id="T_WRONG")
    monkeypatch.setenv("SLACK_WORKSPACE_ID", "T_EXPECTED")
    monkeypatch.setattr(slack_service, "get_slack_adapter", lambda: adapter)
    with TestClient(app) as api:
        client_id = create_client(api, "Workspace Mismatch Client")
        response = api.post(f"/clients/{client_id}/slack-channel")

    assert response.status_code == 409
    assert response.json()["detail"] == "slack_workspace_mismatch"
    assert adapter.channels == []


def test_public_channel_does_not_require_owner_invites(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    monkeypatch.setenv("SLACK_WORKSPACE_ID", adapter.workspace.id)
    monkeypatch.delenv("SLACK_OWNER_USER_IDS", raising=False)
    monkeypatch.setattr(slack_service, "get_slack_adapter", lambda: adapter)
    with TestClient(app) as api:
        client_id = create_client(api, "Missing Slack Owner Client")
        response = api.post(f"/clients/{client_id}/slack-channel")

    assert response.status_code == 200
    assert response.json()["connection"]["connection_status"] == "connected_public"
    assert len(adapter.channels) == 1


def test_notification_delivery_is_idempotent(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    with TestClient(app) as api:
        client_id = create_client(api, "Idempotent Slack Client")
        api.post(f"/clients/{client_id}/slack-channel")
        event = notification_service.NotificationEvent(
            event_key="slack-idempotency-test",
            client_id=client_id,
            category="approval_required",
            importance="medium",
            explanation="A saved proposal needs review.",
            requested_action="Approve or reject the proposal.",
            related_record_type="task",
            related_record_id="task_slack_test",
        )
        with SessionLocal() as database:
            first, first_created = notification_service.deliver_notification(database, event)
            second, second_created = notification_service.deliver_notification(database, event)
            database.commit()
            first_id = first.id
            second_id = second.id
            deliveries = list(
                database.scalars(
                    select(models.SlackDelivery).where(
                        models.SlackDelivery.notification_id == first_id
                    )
                )
            )

    assert first_id == second_id
    assert first_created is True
    assert second_created is False
    assert len(adapter.messages) == 1
    assert len(deliveries) == 1
    assert deliveries[0].status == "delivered"
    assert adapter.messages[0]["operation_key"] == first_id


def test_slack_failure_keeps_internal_record_and_allows_targeted_retry(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter(fail_messages=True)
    connect_fake_slack(monkeypatch, adapter)
    with TestClient(app) as api:
        client_id = create_client(api, "Slack Retry Client")
        api.post(f"/clients/{client_id}/slack-channel")
        event = notification_service.NotificationEvent(
            event_key="slack-failure-test",
            client_id=client_id,
            category="task_failure",
            importance="high",
            explanation="The simulated task failed.",
            requested_action="Review the evidence.",
            related_record_type="execution",
            related_record_id="execution_slack_test",
        )
        with SessionLocal() as database:
            notification, _ = notification_service.deliver_notification(database, event)
            database.commit()
            database.refresh(notification)
            failed = database.scalar(
                select(models.SlackDelivery).where(
                    models.SlackDelivery.notification_id == notification.id
                )
            )
            assert failed.status == "failed"
            assert database.get(models.Notification, notification.id) is not None
        adapter.fail_messages = False
        retried = api.post(f"/notifications/{notification.id}/slack-delivery")

    assert retried.status_code == 200
    assert retried.json()["status"] == "delivered"
    assert retried.json()["attempt_count"] == 2
    assert len(adapter.messages) == 1


def test_messages_never_cross_client_channels(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    with TestClient(app) as api:
        first_id = create_client(api, "First Slack Separation Client")
        second_id = create_client(api, "Second Slack Separation Client")
        first_connection = api.post(f"/clients/{first_id}/slack-channel").json()["connection"]
        second_connection = api.post(f"/clients/{second_id}/slack-channel").json()["connection"]
        with SessionLocal() as database:
            for client_id, suffix in [(first_id, "first"), (second_id, "second")]:
                notification_service.deliver_notification(
                    database,
                    notification_service.NotificationEvent(
                        event_key=f"slack-separation-{suffix}",
                        client_id=client_id,
                        category="approval_required",
                        importance="medium",
                        explanation=f"{suffix.title()} client approval.",
                        requested_action="Review only this client's record.",
                        related_record_type="task",
                        related_record_id=f"task_{suffix}",
                    ),
                )
            database.commit()

    by_channel = {message["channel_id"]: message["text"] for message in adapter.messages}
    assert "First Slack Separation Client" in by_channel[first_connection["channel_id"]]
    assert "Second Slack Separation Client" not in by_channel[first_connection["channel_id"]]
    assert "Second Slack Separation Client" in by_channel[second_connection["channel_id"]]
    assert "First Slack Separation Client" not in by_channel[second_connection["channel_id"]]


def test_slack_parser_prepares_scoped_content_packet_types() -> None:
    from app.slack_action_service import detect_owner_action

    local_page = detect_owner_action(
        "prepare content task task_1234abcd as local page", has_mapped_client=True
    )
    blog = detect_owner_action(
        "prepare SEO task task_5678efgh for article", has_mapped_client=True
    )
    assert local_page is not None
    assert local_page.action_type == "prepare_content_task"
    assert local_page.seo_work_type == "local_page"
    assert blog is not None
    assert blog.seo_work_type == "blog"
