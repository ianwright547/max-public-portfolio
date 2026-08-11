"""Add explicit durable agency- and client-scoped Slack memories."""

from alembic import op
import sqlalchemy as sa


revision = "0009_slack_memories"
down_revision = "0008_slack_conversation_turns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "slack_memories" in inspector.get_table_names():
        return
    op.create_table(
        "slack_memories",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("workspace_id", sa.String(length=40), nullable=False),
        sa.Column("client_id", sa.String(length=16), nullable=True),
        sa.Column("memory_key", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=40), nullable=False),
        sa.Column("updated_by", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("workspace_id", "client_id", "memory_key", "category", "is_active", "updated_at"):
        op.create_index(f"ix_slack_memories_{column}", "slack_memories", [column])


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
