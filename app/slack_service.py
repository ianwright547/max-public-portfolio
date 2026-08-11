"""Replaceable Slack adapter and safe client-channel delivery rules."""

import os
import re
import unicodedata
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models


logger = logging.getLogger(__name__)


class SlackIntegrationError(RuntimeError):
    """A safe Slack error that never contains a credential."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class SlackClientMismatchError(SlackIntegrationError):
    """The Slack workspace or channel does not match the saved Max client."""


@dataclass(frozen=True)
class SlackWorkspace:
    id: str
    name: str
    bot_user_id: str


@dataclass(frozen=True)
class SlackUser:
    id: str
    deleted: bool = False
    is_bot: bool = False


@dataclass(frozen=True)
class SlackChannel:
    id: str
    name: str
    is_archived: bool = False


@dataclass(frozen=True)
class SlackMessage:
    channel_id: str
    timestamp: str


class SlackAdapter(Protocol):
    """The small boundary a future Slack SDK or mock must implement."""

    def verify_workspace(self) -> SlackWorkspace: ...

    def get_user(self, user_id: str) -> SlackUser: ...

    def create_private_channel(self, channel_name: str) -> SlackChannel: ...

    def create_public_channel(self, channel_name: str) -> SlackChannel: ...

    def archive_channel(self, channel_id: str) -> None: ...

    def rename_channel(self, channel_id: str, channel_name: str) -> SlackChannel: ...

    def get_channel(self, channel_id: str) -> SlackChannel: ...

    def invite_users(self, channel_id: str, user_ids: list[str]) -> None: ...

    def post_message(self, channel_id: str, text: str, operation_key: str) -> SlackMessage: ...

    def post_approval_message(
        self, channel_id: str, text: str, task_id: str, operation_key: str
    ) -> SlackMessage: ...


class SlackHttpAdapter:
    """Call Slack Web API with a bot token supplied only through the environment."""

    def __init__(self, token: str, timeout_seconds: float = 10.0) -> None:
        if not token:
            raise SlackIntegrationError("slack_token_missing")
        self._token = token
        self._timeout_seconds = timeout_seconds

    def _call(self, method: str, payload: dict, *, form_encoded: bool = False) -> dict:
        try:
            request_body = {"data": payload} if form_encoded else {"json": payload}
            response = httpx.post(
                f"https://slack.com/api/{method}",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=self._timeout_seconds,
                **request_body,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise SlackIntegrationError("slack_temporarily_unavailable", retryable=True) from error
        if response.status_code == 429:
            raise SlackIntegrationError("slack_rate_limited", retryable=True)
        if response.status_code >= 500:
            raise SlackIntegrationError("slack_temporarily_unavailable", retryable=True)
        try:
            result = response.json()
        except ValueError as error:
            raise SlackIntegrationError("slack_invalid_response", retryable=True) from error
        if not result.get("ok"):
            code = str(result.get("error", "slack_unknown_error"))
            retryable = code in {"fatal_error", "internal_error", "service_unavailable"}
            raise SlackIntegrationError(code, retryable=retryable)
        return result

    def verify_workspace(self) -> SlackWorkspace:
        result = self._call("auth.test", {})
        return SlackWorkspace(
            id=str(result["team_id"]),
            name=str(result.get("team", "Slack workspace")),
            bot_user_id=str(result["user_id"]),
        )

    def get_user(self, user_id: str) -> SlackUser:
        result = self._call("users.info", {"user": user_id}, form_encoded=True)
        user = result.get("user") or {}
        return SlackUser(
            id=str(user.get("id", "")),
            deleted=bool(user.get("deleted", False)),
            is_bot=bool(user.get("is_bot", False)),
        )

    def create_private_channel(self, channel_name: str) -> SlackChannel:
        result = self._call(
            "conversations.create",
            {"name": channel_name, "is_private": True},
        )
        channel = result["channel"]
        return SlackChannel(id=str(channel["id"]), name=str(channel["name"]))

    def create_public_channel(self, channel_name: str) -> SlackChannel:
        result = self._call(
            "conversations.create",
            {"name": channel_name, "is_private": False},
        )
        channel = result["channel"]
        return SlackChannel(id=str(channel["id"]), name=str(channel["name"]))

    def archive_channel(self, channel_id: str) -> None:
        self._call("conversations.archive", {"channel": channel_id})

    def rename_channel(self, channel_id: str, channel_name: str) -> SlackChannel:
        result = self._call(
            "conversations.rename",
            {"channel": channel_id, "name": channel_name},
        )
        channel = result["channel"]
        return SlackChannel(id=str(channel["id"]), name=str(channel["name"]))

    def get_channel(self, channel_id: str) -> SlackChannel:
        result = self._call(
            "conversations.info", {"channel": channel_id}, form_encoded=True
        )
        channel = result["channel"]
        return SlackChannel(
            id=str(channel["id"]),
            name=str(channel["name"]),
            is_archived=bool(channel.get("is_archived", False)),
        )

    def invite_users(self, channel_id: str, user_ids: list[str]) -> None:
        if user_ids:
            self._call(
                "conversations.invite",
                {"channel": channel_id, "users": ",".join(user_ids)},
            )

    def post_message(self, channel_id: str, text: str, operation_key: str) -> SlackMessage:
        result = self._call(
            "chat.postMessage",
            {
                "channel": channel_id,
                "text": text,
                "client_msg_id": operation_key,
                "unfurl_links": False,
                "unfurl_media": False,
            },
        )
        return SlackMessage(channel_id=str(result["channel"]), timestamp=str(result["ts"]))

    def post_approval_message(
        self, channel_id: str, text: str, task_id: str, operation_key: str
    ) -> SlackMessage:
        result = self._call(
            "chat.postMessage",
            {
                "channel": channel_id,
                "text": text,
                "client_msg_id": operation_key,
                "unfurl_links": False,
                "unfurl_media": False,
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": text}},
                    {
                        "type": "actions",
                        "block_id": f"max_task_decision_{task_id}",
                        "elements": [
                            {
                                "type": "button",
                                "action_id": "max_task_approve",
                                "text": {"type": "plain_text", "text": "Approve"},
                                "style": "primary",
                                "value": task_id,
                                "confirm": {
                                    "title": {"type": "plain_text", "text": "Approve task?"},
                                    "text": {"type": "mrkdwn", "text": "This records approval in Max. It does not start work by itself."},
                                    "confirm": {"type": "plain_text", "text": "Approve"},
                                    "deny": {"type": "plain_text", "text": "Cancel"},
                                },
                            },
                            {
                                "type": "button",
                                "action_id": "max_task_reject",
                                "text": {"type": "plain_text", "text": "Reject"},
                                "style": "danger",
                                "value": task_id,
                                "confirm": {
                                    "title": {"type": "plain_text", "text": "Reject task?"},
                                    "text": {"type": "mrkdwn", "text": "This records a rejection in Max."},
                                    "confirm": {"type": "plain_text", "text": "Reject"},
                                    "deny": {"type": "plain_text", "text": "Cancel"},
                                },
                            },
                        ],
                    },
                ],
            },
        )
        return SlackMessage(channel_id=str(result["channel"]), timestamp=str(result["ts"]))


def get_slack_adapter() -> SlackAdapter:
    """Build the live adapter only when Slack is intentionally configured."""
    return SlackHttpAdapter(os.getenv("SLACK_BOT_TOKEN", "").strip())


def slack_owner_user_ids() -> list[str]:
    """Read optional agency-owner Slack member IDs without storing them in client records."""
    return [
        user_id.strip()
        for user_id in os.getenv("SLACK_OWNER_USER_IDS", "").split(",")
        if user_id.strip()
    ]


def slack_authorized_user_ids(database: Session, capability: str = "client_operations") -> set[str]:
    """Return configured legacy owners plus active mapped members with a capability."""
    from app.agency_access_service import has_capability

    ids = set(slack_owner_user_ids())
    members = database.scalars(
        select(models.AgencyMember).where(
            models.AgencyMember.active.is_(True),
            models.AgencyMember.slack_user_id.is_not(None),
        )
    )
    ids.update(member.slack_user_id for member in members if member.slack_user_id and has_capability(member.role, capability))
    return ids


def resolve_client_channel_connection(
    database: Session,
    workspace_id: str,
    channel_id: str,
    adapter: SlackAdapter,
    slack_user_id: Optional[str] = None,
) -> Optional[models.SlackChannelConnection]:
    """Resolve a mapped channel and safely repair or adopt one owner-verified channel."""
    direct = database.scalar(
        select(models.SlackChannelConnection).where(
            models.SlackChannelConnection.channel_id == channel_id,
            models.SlackChannelConnection.workspace_id == workspace_id,
        )
    )
    if direct is not None:
        return direct

    try:
        current = adapter.get_channel(channel_id)
    except SlackIntegrationError as error:
        # A signed app_mention still supports owner-only general chat when a
        # channel cannot be inspected (for example, an invited private channel
        # on an older installation without groups:read).
        if error.code in {"channel_not_found", "missing_scope"}:
            return None
        raise
    candidates = list(
        database.scalars(
            select(models.SlackChannelConnection).where(
                models.SlackChannelConnection.workspace_id == workspace_id,
                models.SlackChannelConnection.channel_name == current.name,
                models.SlackChannelConnection.connection_status.in_(
                    {"connected", "connected_public"}
                ),
            )
        )
    )
    candidate = candidates[0] if len(candidates) == 1 else None
    if candidate is None:
        # An agency owner may adopt an otherwise unmapped channel only when its
        # exact Slack name maps to one and only one deterministic client slug.
        if slack_user_id not in slack_owner_user_ids():
            logger.info(
                "slack_channel_adoption status=denied reason=owner_required channel=%s",
                channel_id,
            )
            return None
        matching_clients = [
            client
            for client in database.scalars(select(models.Client))
            if client_channel_name(client) == current.name
        ]
        if len(matching_clients) != 1:
            logger.info(
                "slack_channel_adoption status=denied reason=client_match_count channel=%s count=%s",
                channel_id,
                len(matching_clients),
            )
            return None
        client = matching_clients[0]
        candidate = database.scalar(
            select(models.SlackChannelConnection).where(
                models.SlackChannelConnection.client_id == client.id
            )
        )
        if candidate is None:
            workspace = adapter.verify_workspace()
            if workspace.id != workspace_id:
                raise SlackClientMismatchError("slack_workspace_mismatch")
            candidate = models.SlackChannelConnection(
                client_id=client.id,
                workspace_id=workspace.id,
                workspace_name=workspace.name,
                channel_id=current.id,
                channel_name=current.name,
                connection_status="connected_public",
                last_verified_at=datetime.utcnow(),
            )
            database.add(candidate)
            database.flush()
            logger.info(
                "slack_channel_adoption status=adopted channel=%s client=%s",
                channel_id,
                client.id,
            )
            return candidate
    try:
        saved = adapter.get_channel(candidate.channel_id)
    except SlackIntegrationError as error:
        if error.code != "channel_not_found":
            raise
    else:
        # Never move a mapping away from another live channel.
        if not saved.is_archived:
            logger.info(
                "slack_channel_adoption status=denied reason=existing_channel_live channel=%s saved_channel=%s",
                channel_id,
                candidate.channel_id,
            )
            return None
    candidate.channel_id = current.id
    candidate.channel_name = current.name
    candidate.last_verified_at = datetime.utcnow()
    candidate.last_error = None
    database.flush()
    logger.info(
        "slack_channel_adoption status=repaired channel=%s client=%s",
        channel_id,
        candidate.client_id,
    )
    return candidate


def client_channel_name(client: models.Client) -> str:
    """Make a short, readable Slack-safe display name."""
    normalized = unicodedata.normalize("NFKD", client.business_name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-") or "client"
    return slug[:80].rstrip("-") or "client"


def rename_client_channel(
    database: Session,
    client_id: str,
    adapter: Optional[SlackAdapter] = None,
) -> models.SlackChannelConnection:
    """Rename the mapped Slack channel without changing its backend identity."""
    client = database.get(models.Client, client_id)
    if client is None:
        raise ValueError("client_not_found")
    connection = database.scalar(
        select(models.SlackChannelConnection).where(
            models.SlackChannelConnection.client_id == client_id
        )
    )
    if connection is None:
        raise SlackIntegrationError("slack_channel_not_connected")
    slack = adapter or get_slack_adapter()
    renamed = slack.rename_channel(connection.channel_id, client_channel_name(client))
    if renamed.id != connection.channel_id:
        raise SlackClientMismatchError("slack_response_channel_mismatch")
    connection.channel_name = renamed.name
    connection.last_verified_at = datetime.utcnow()
    connection.last_error = None
    database.flush()
    return connection


def recreate_client_public_channel(
    database: Session,
    client_id: str,
    adapter: Optional[SlackAdapter] = None,
) -> models.SlackChannelConnection:
    """Archive the private channel and replace it with a public channel."""
    client = database.get(models.Client, client_id)
    if client is None:
        raise ValueError("client_not_found")
    connection = database.scalar(
        select(models.SlackChannelConnection).where(
            models.SlackChannelConnection.client_id == client_id
        )
    )
    if connection is None:
        raise SlackIntegrationError("slack_channel_not_connected")
    slack = adapter or get_slack_adapter()
    workspace = slack.verify_workspace()
    expected_workspace_id = os.getenv("SLACK_WORKSPACE_ID", "").strip()
    if expected_workspace_id and workspace.id != expected_workspace_id:
        raise SlackClientMismatchError("slack_workspace_mismatch")
    old_channel_id = connection.channel_id
    public_name = f"{client_channel_name(client)}-public"[:80].rstrip("-")
    # The first attempt may already have archived the old private channel.
    # Archived names remain reserved, so public replacements use a clear suffix.
    if connection.connection_status != "connected_public":
        try:
            slack.rename_channel(old_channel_id, f"archived-{client.id.removeprefix('client_')}")
            slack.archive_channel(old_channel_id)
        except SlackIntegrationError as error:
            if error.code not in {"already_archived", "is_archived", "channel_not_found"}:
                raise
    channel = slack.create_public_channel(public_name)
    slack.invite_users(channel.id, slack_owner_user_ids())
    connection.workspace_id = workspace.id
    connection.workspace_name = workspace.name
    connection.channel_id = channel.id
    connection.channel_name = channel.name
    connection.connection_status = "connected_public"
    connection.last_verified_at = datetime.utcnow()
    connection.last_error = None
    database.flush()
    return connection


def connect_client_channel(
    database: Session,
    client_id: str,
    adapter: Optional[SlackAdapter] = None,
) -> tuple[models.SlackChannelConnection, bool]:
    """Create and save exactly one verified public Slack channel for a client."""
    client = database.get(models.Client, client_id)
    if client is None:
        raise ValueError("client_not_found")
    slack = adapter or get_slack_adapter()
    workspace = slack.verify_workspace()
    expected_workspace_id = os.getenv("SLACK_WORKSPACE_ID", "").strip()
    if expected_workspace_id and workspace.id != expected_workspace_id:
        raise SlackClientMismatchError("slack_workspace_mismatch")

    existing = database.scalar(
        select(models.SlackChannelConnection).where(
            models.SlackChannelConnection.client_id == client_id
        )
    )
    if existing is not None:
        if existing.workspace_id != workspace.id:
            raise SlackClientMismatchError("saved_channel_workspace_mismatch")
        existing.last_verified_at = datetime.utcnow()
        existing.last_error = None
        _ensure_daily_plan_job(database, client.id)
        database.flush()
        return existing, False

    owner_user_ids = slack_owner_user_ids()
    channel = slack.create_public_channel(client_channel_name(client))
    # Public channels do not require invitations, but invite configured owners
    # when available so their Slack membership is explicit and auditable.
    if owner_user_ids:
        slack.invite_users(channel.id, owner_user_ids)
    connection = models.SlackChannelConnection(
        client_id=client.id,
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        channel_id=channel.id,
        channel_name=channel.name,
        connection_status="connected_public",
        last_verified_at=datetime.utcnow(),
    )
    database.add(connection)
    _ensure_daily_plan_job(database, client.id)
    database.flush()
    return connection, True


def _ensure_daily_plan_job(database: Session, client_id: str) -> models.ScheduledJob:
    """Give every Slack-connected client one quiet, deduplicated daily plan job."""
    job = database.scalar(
        select(models.ScheduledJob).where(
            models.ScheduledJob.job_key == f"daily-plan:{client_id}"
        )
    )
    if job is None:
        job = models.ScheduledJob(
            job_key=f"daily-plan:{client_id}",
            job_type="daily_client_plan",
            client_id=client_id,
            interval_minutes=1440,
            next_run_at=datetime.utcnow() + timedelta(days=1),
            enabled=True,
        )
        database.add(job)
    return job


def slack_notification_text(client: models.Client, notification: models.Notification) -> str:
    """Create a concise, factual message without pretending proposed work is complete."""
    category = notification.category.replace("_", " ").title()
    return (
        f"*{category} · {client.business_name}*\n"
        f"{notification.explanation}\n\n"
        f"*Requested action:* {notification.requested_action}\n"
        f"*Reference:* {notification.related_record_type} `{notification.related_record_id}`"
    )


def report_delivery_text(client: models.Client, report: models.Report, report_url: Optional[str] = None) -> str:
    """Describe an approved immutable report and link to its client share PDF."""
    base_url = os.getenv("MAX_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if report_url is None:
        report_path = f"/reports/{report.id}/pdf"
        report_url = f"{base_url}{report_path}" if base_url else report_path
    return (
        f"*Approved client report · {client.business_name}*\n"
        f"{report.title}\n"
        f"Reporting period: {report.period_start.isoformat()} to {report.period_end.isoformat()}\n\n"
        f"Download the approved PDF: {report_url}\n"
        f"Reference: report `{report.id}`"
    )


def deliver_approved_report(
    database: Session,
    report: models.Report,
    adapter: Optional[SlackAdapter] = None,
) -> models.ReportDelivery:
    """Deliver an approved client report once and retain failed attempts for retry."""
    if report.report_type != "client":
        raise SlackIntegrationError("client_report_required")
    if report.status != "approved":
        raise SlackIntegrationError("report_approval_required")
    connection = database.scalar(
        select(models.SlackChannelConnection).where(
            models.SlackChannelConnection.client_id == report.client_id
        )
    )
    if connection is None or connection.connection_status not in {"connected", "connected_public"}:
        raise SlackIntegrationError("slack_channel_not_connected")
    operation_key = f"report-delivery:{report.id}:slack"
    existing = database.scalar(
        select(models.ReportDelivery).where(models.ReportDelivery.operation_key == operation_key)
    )
    if existing is not None and existing.status == "delivered":
        return existing
    delivery = existing or models.ReportDelivery(
        operation_key=operation_key,
        report_id=report.id,
        client_id=report.client_id,
        channel_connection_id=connection.id,
        channel_id=connection.channel_id,
        status="pending",
    )
    if existing is None:
        database.add(delivery)
        database.flush()
    if (
        delivery.client_id != connection.client_id
        or delivery.channel_connection_id != connection.id
        or delivery.channel_id != connection.channel_id
    ):
        raise SlackClientMismatchError("report_delivery_client_mismatch")

    delivery.attempt_count += 1
    delivery.last_attempt_at = datetime.utcnow()
    client = database.get(models.Client, report.client_id)
    from app.report_share_service import issue_report_share_token, share_path

    share_token = issue_report_share_token(report)
    share_path_value = share_path(report, share_token)
    base_url = os.getenv("MAX_PUBLIC_BASE_URL", "").strip().rstrip("/")
    share_url = f"{base_url}{share_path_value}" if base_url else share_path_value
    try:
        slack = adapter or get_slack_adapter()
        result = slack.post_message(
            connection.channel_id,
            report_delivery_text(client, report, share_url),
            operation_key,
        )
        if result.channel_id != connection.channel_id:
            raise SlackClientMismatchError("slack_response_channel_mismatch")
    except SlackIntegrationError as error:
        delivery.status = "failed"
        delivery.last_error = error.code
        database.flush()
        return delivery

    delivery.status = "delivered"
    delivery.message_timestamp = result.timestamp
    delivery.last_error = None
    delivery.delivered_at = datetime.utcnow()
    database.flush()
    return delivery


def deliver_saved_notification(
    database: Session,
    notification: models.Notification,
    adapter: Optional[SlackAdapter] = None,
) -> Optional[models.SlackDelivery]:
    """Deliver once; save failures without losing the internal notification."""
    connection = database.scalar(
        select(models.SlackChannelConnection).where(
            models.SlackChannelConnection.client_id == notification.client_id
        )
    )
    if connection is None:
        return None
    if connection.connection_status not in {"connected", "connected_public"}:
        return None
    existing = database.scalar(
        select(models.SlackDelivery).where(
            models.SlackDelivery.notification_id == notification.id
        )
    )
    if existing is not None and existing.status == "delivered":
        return existing
    delivery = existing or models.SlackDelivery(
        notification_id=notification.id,
        client_id=notification.client_id,
        channel_connection_id=connection.id,
        channel_id=connection.channel_id,
        status="pending",
    )
    if existing is None:
        database.add(delivery)
        database.flush()
    if delivery.client_id != connection.client_id or delivery.channel_id != connection.channel_id:
        raise SlackClientMismatchError("slack_delivery_client_mismatch")

    delivery.attempt_count += 1
    delivery.last_attempt_at = datetime.utcnow()
    client = database.get(models.Client, notification.client_id)
    try:
        slack = adapter or get_slack_adapter()
        text = slack_notification_text(client, notification)
        if notification.category == "approval_required" and notification.related_record_type == "task" and hasattr(slack, "post_approval_message"):
            result = slack.post_approval_message(
                connection.channel_id,
                text,
                notification.related_record_id,
                notification.id,
            )
        else:
            result = slack.post_message(connection.channel_id, text, notification.id)
        if result.channel_id != connection.channel_id:
            raise SlackClientMismatchError("slack_response_channel_mismatch")
    except SlackIntegrationError as error:
        delivery.status = "failed"
        delivery.last_error = error.code
        database.flush()
        return delivery

    delivery.status = "delivered"
    delivery.message_timestamp = result.timestamp
    delivery.last_error = None
    delivery.delivered_at = datetime.utcnow()
    database.flush()
    return delivery
