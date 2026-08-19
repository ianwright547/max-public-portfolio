import json

from app import slack_service
from scripts import check_slack_provider


def _configure(monkeypatch, workspace_id="T_MAX"):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "DEMO_SLACK_TOKEN")
    monkeypatch.setenv("SLACK_WORKSPACE_ID", workspace_id)
    monkeypatch.setenv("SLACK_OWNER_USER_IDS", "U_OWNER,U_BACKUP")


def test_probe_verifies_workspace_without_printing_token(monkeypatch, capsys):
    _configure(monkeypatch)
    adapter = type(
        "Adapter",
        (),
        {
            "verify_workspace": lambda self: slack_service.SlackWorkspace("T_MAX", "Max", "U_BOT"),
            "get_user": lambda self, user_id: slack_service.SlackUser(user_id),
        },
    )()
    monkeypatch.setattr(check_slack_provider, "get_slack_adapter", lambda: adapter)

    assert check_slack_provider.main() == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["status"] == "verified"
    assert payload["owner_ids_configured"] == 2
    assert "DEMO_SLACK_TOKEN" not in output


def test_probe_rejects_workspace_mismatch(monkeypatch, capsys):
    _configure(monkeypatch, "T_EXPECTED")
    adapter = type(
        "Adapter",
        (),
        {
            "verify_workspace": lambda self: slack_service.SlackWorkspace("T_OTHER", "Other", "U_BOT"),
            "get_user": lambda self, user_id: slack_service.SlackUser(user_id),
        },
    )()
    monkeypatch.setattr(check_slack_provider, "get_slack_adapter", lambda: adapter)

    assert check_slack_provider.main() == 1
    assert capsys.readouterr().err.strip() == "Slack verification failed: slack_workspace_mismatch"


def test_probe_suppresses_provider_details(monkeypatch, capsys):
    _configure(monkeypatch)

    def fail(self):
        raise slack_service.SlackIntegrationError("invalid_auth")

    monkeypatch.setattr(
        check_slack_provider,
        "get_slack_adapter",
        lambda: type(
            "Adapter",
            (),
            {
                "verify_workspace": fail,
                "get_user": lambda self, user_id: slack_service.SlackUser(user_id),
            },
        )(),
    )
    assert check_slack_provider.main() == 1
    assert capsys.readouterr().err.strip() == "Slack verification failed: invalid_auth"


def test_probe_requires_owner_ids(monkeypatch, capsys):
    _configure(monkeypatch)
    monkeypatch.delenv("SLACK_OWNER_USER_IDS")
    assert check_slack_provider.main() == 1
    assert capsys.readouterr().err.strip() == "Slack verification failed: slack_owner_user_ids_missing"


def test_probe_rejects_deleted_owner(monkeypatch, capsys):
    _configure(monkeypatch)
    adapter = type(
        "Adapter",
        (),
        {
            "verify_workspace": lambda self: slack_service.SlackWorkspace("T_MAX", "Max", "U_BOT"),
            "get_user": lambda self, user_id: slack_service.SlackUser(user_id, deleted=True),
        },
    )()
    monkeypatch.setattr(check_slack_provider, "get_slack_adapter", lambda: adapter)
    assert check_slack_provider.main() == 1
    assert capsys.readouterr().err.strip() == "Slack verification failed: slack_owner_user_inactive"
