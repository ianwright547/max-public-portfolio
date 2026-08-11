"""Slack has cheap 24-hour continuity plus explicit durable scoped memory."""

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app import models, slack_conversation_service, slack_memory_service, slack_service
from app.database import SessionLocal, create_database
from tests.test_slack import (
    FakeSlackAdapter,
    connect_fake_slack,
    create_client,
    post_signed_slack_event,
)


def test_conversation_history_expires_after_24_hours_and_stays_bounded() -> None:
    create_database()
    workspace = f"T_MEMORY_{uuid4().hex[:8]}"
    channel = f"C_MEMORY_{uuid4().hex[:8]}"
    with SessionLocal() as database:
        old = models.SlackConversationTurn(
            event_id=f"Ev_old_{uuid4().hex}",
            workspace_id=workspace,
            channel_id=channel,
            thread_ts=None,
            slack_user_id="U_MEMORY",
            question="old question",
            answer="old answer",
            result_status="responded",
            created_at=datetime.utcnow() - timedelta(hours=25),
        )
        recent = models.SlackConversationTurn(
            event_id=f"Ev_recent_{uuid4().hex}",
            workspace_id=workspace,
            channel_id=channel,
            thread_ts=None,
            slack_user_id="U_MEMORY",
            question="recent " + "q" * 3000,
            answer="recent " + "a" * 3000,
            result_status="responded",
            created_at=datetime.utcnow() - timedelta(hours=1),
        )
        database.add_all([old, recent])
        database.commit()
        history = slack_conversation_service.conversation_history(
            database,
            workspace_id=workspace,
            channel_id=channel,
            thread_ts=None,
        )

    assert len(history) == 1
    assert history[0]["question"].startswith("recent")
    assert len(history[0]["question"]) <= 1200
    assert len(history[0]["answer"]) <= 1800


def test_durable_memory_is_client_scoped_relevant_and_compact() -> None:
    create_database()
    workspace = f"T_SCOPE_{uuid4().hex[:8]}"
    with SessionLocal() as database:
        first = models.Client(
            business_name=f"Memory First {uuid4().hex[:6]}",
            service_start_date=datetime.utcnow().date(),
        )
        second = models.Client(
            business_name=f"Memory Second {uuid4().hex[:6]}",
            service_start_date=datetime.utcnow().date(),
        )
        database.add_all([first, second])
        database.flush()
        style, _ = slack_memory_service.save_memory(
            database,
            workspace_id=workspace,
            client_id=first.id,
            slack_user_id="U_MEMORY",
            content="Use short direct answers with concrete next steps.",
            category="style",
        )
        bookings, _ = slack_memory_service.save_memory(
            database,
            workspace_id=workspace,
            client_id=first.id,
            slack_user_id="U_MEMORY",
            content="The client calls appointments bookings.",
        )
        slack_memory_service.save_memory(
            database,
            workspace_id=workspace,
            client_id=second.id,
            slack_user_id="U_MEMORY",
            content="This belongs only to the other client.",
        )
        database.commit()
        retrieved = slack_memory_service.relevant_memories(
            database,
            workspace_id=workspace,
            client_id=first.id,
            question="How should I describe appointment bookings?",
        )

    assert {item["id"] for item in retrieved} == {style.id, bookings.id}
    assert sum(len(item["content"]) for item in retrieved) <= 2400
    assert all("other client" not in item["content"] for item in retrieved)


def test_signed_slack_can_store_use_update_list_and_forget_memory(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    captured_contexts: list[dict] = []

    def answer(question: str, *, client_context=None, conversation_history=None):
        captured_contexts.append(client_context or {})
        return slack_conversation_service.SlackConversationAnswer(
            text=f"Answer to: {question}",
            model="gpt-test",
            input_tokens=20,
            output_tokens=10,
            estimated_cost_usd=0.0001,
        )

    monkeypatch.setattr(slack_conversation_service, "answer_question", answer)
    with TestClient(app) as api:
        client_id = create_client(api, f"Durable Memory {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]

        def mention(text: str):
            return post_signed_slack_event(
                api,
                {
                    "type": "event_callback",
                    "team_id": adapter.workspace.id,
                    "event_id": f"Ev_memory_{uuid4().hex}",
                    "event": {
                        "type": "app_mention",
                        "user": "U_CHANNEL_MEMBER",
                        "channel": connection["channel_id"],
                        "text": f"<@U_BOT> {text}",
                    },
                },
            )

        saved = mention("remember that this client calls appointments bookings")
        style_one = mention("update your response style to concise and direct")
        style_two = mention("update your response style to warm, concise, and direct")
        asked = mention("how should I discuss appointment bookings?")
        listed = mention("what do you remember?")
        with SessionLocal() as database:
            memories = list(
                database.scalars(
                    select(models.SlackMemory).where(
                        models.SlackMemory.client_id == client_id,
                        models.SlackMemory.is_active.is_(True),
                    )
                )
            )
            general = next(item for item in memories if item.category == "general")
            style = [item for item in memories if item.category == "style"]
        forgotten = mention(f"forget memory {general.id}")
        with SessionLocal() as database:
            general_after = database.get(models.SlackMemory, general.id)

    assert all(item.status_code == 200 for item in (saved, style_one, style_two, asked, listed, forgotten))
    assert len(style) == 1
    assert style[0].content == "warm, concise, and direct"
    durable = captured_contexts[-1]["durable_memory"]
    assert any("appointments bookings" in item["content"] for item in durable)
    assert any("warm, concise" in item["content"] for item in durable)
    assert general.id in adapter.messages[-2]["text"]
    assert general_after.is_active is False
    assert "Forgot durable memory" in adapter.messages[-1]["text"]


def test_credentials_are_never_saved_as_memory(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as api:
        client_id = create_client(api, f"Secret Memory {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_secret_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_CHANNEL_MEMBER",
                    "channel": connection["channel_id"],
                    "text": "<@U_BOT> remember that api_key=sk-proj-abcdefghijklmnop123456",
                },
            },
        )
        with SessionLocal() as database:
            memories = list(
                database.scalars(
                    select(models.SlackMemory).where(models.SlackMemory.client_id == client_id)
                )
            )

    assert response.status_code == 200
    assert memories == []
    assert "will not store credentials" in adapter.messages[-1]["text"]
