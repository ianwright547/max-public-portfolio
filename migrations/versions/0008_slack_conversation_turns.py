"""Persist redacted Slack thread turns for bounded follow-up context."""

from alembic import op
import sqlalchemy as sa


revision = "0008_slack_conversation_turns"
down_revision = "0007_agency_ai_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "slack_conversation_turns" in inspector.get_table_names():
        return
    op.create_table(
        "slack_conversation_turns",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("event_id", sa.String(length=80), nullable=False),
        sa.Column("workspace_id", sa.String(length=40), nullable=False),
        sa.Column("channel_id", sa.String(length=40), nullable=False),
        sa.Column("thread_ts", sa.String(length=40), nullable=True),
        sa.Column("slack_user_id", sa.String(length=40), nullable=False),
        sa.Column("client_id", sa.String(length=16), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=True),
        sa.Column("result_status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    for column in ("event_id", "workspace_id", "channel_id", "thread_ts", "slack_user_id", "client_id", "created_at"):
        op.create_index(f"ix_slack_conversation_turns_{column}", "slack_conversation_turns", [column])


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
