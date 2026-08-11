from datetime import date
from uuid import uuid4

from app import models
from app.client_provider_verification import verify_client_providers
from app.database import SessionLocal, create_database
from app.readiness_service import build_client_launch_readiness


class FakeSlackChannel:
    id = "C_CLIENT"
    name = "client-channel"
    is_archived = False


class FakeSlackWorkspace:
    id = "T_CLIENT"
    name = "Workspace"
    bot_user_id = "U_BOT"


class FakeSlack:
    def verify_workspace(self):
        return FakeSlackWorkspace()

    def get_channel(self, channel_id):
        return FakeSlackChannel()


def test_client_provider_verification_persists_safe_success_and_audit(monkeypatch) -> None:
    create_database()
    monkeypatch.setattr("app.client_provider_verification.get_slack_adapter", lambda: FakeSlack())
    with SessionLocal() as database:
        client = models.Client(business_name=f"Provider probe {uuid4().hex}", service_start_date=date.today())
        database.add(client)
        database.flush()
        connection = models.SlackChannelConnection(
            client_id=client.id,
            workspace_id="T_CLIENT",
            workspace_name="Workspace",
            channel_id="C_CLIENT",
            channel_name="client-channel",
        )
        database.add(connection)
        database.flush()
        result = verify_client_providers(database, client.id)
        database.commit()

        assert result["status"] == "verified"
        assert result["summary"] == {"verified": 1, "failed": 0, "probed": 1}
        assert connection.connection_status == "connected"
        readiness = build_client_launch_readiness(database, client.id)
        live_check = next(item for item in readiness["recommended_checks"] if item["key"] == "live_provider_verification")
        assert live_check["status"] == "passed"
        events = list(
            database.query(models.AuditEvent)
            .filter(models.AuditEvent.event_type == "client_provider_verification")
        )
        assert events[-1].details == {
            "provider": "slack",
            "status": "verified",
            "code": None,
            "retryable": False,
        }
        assert "token" not in str(result).casefold()


def test_client_provider_verification_marks_mismatch_without_raw_provider_error(monkeypatch) -> None:
    create_database()

    class MismatchSlack(FakeSlack):
        def verify_workspace(self):
            workspace = FakeSlackWorkspace()
            workspace.id = "T_OTHER"
            return workspace

    monkeypatch.setattr("app.client_provider_verification.get_slack_adapter", lambda: MismatchSlack())
    with SessionLocal() as database:
        client = models.Client(business_name=f"Provider mismatch {uuid4().hex}", service_start_date=date.today())
        database.add(client)
        database.flush()
        connection = models.SlackChannelConnection(
            client_id=client.id,
            workspace_id="T_CLIENT",
            workspace_name="Workspace",
            channel_id="C_CLIENT_MISMATCH",
            channel_name="client-channel",
        )
        database.add(connection)
        database.flush()
        result = verify_client_providers(database, client.id)

        assert result["status"] == "failed"
        assert result["results"][0]["code"] == "slack_workspace_mismatch"
        assert connection.connection_status == "error"
        assert "authorization" not in str(result).casefold()
