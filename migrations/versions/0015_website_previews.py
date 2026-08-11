"""Persist generated website previews before any external commit."""

from alembic import op
import sqlalchemy as sa


revision = "0015_website_previews"
down_revision = "0014_client_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "website_previews" in inspector.get_table_names():
        return
    op.create_table(
        "website_previews",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("operation_key", sa.String(length=120), nullable=False),
        sa.Column("client_id", sa.String(length=16), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("task_id", sa.String(length=24), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("packet_id", sa.String(length=28), sa.ForeignKey("codex_work_packets.id"), nullable=False),
        sa.Column("model_role", sa.String(length=40), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("file_manifest", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("generated_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("operation_key"),
    )
    op.create_index("ix_website_previews_operation_key", "website_previews", ["operation_key"])
    op.create_index("ix_website_previews_client_id", "website_previews", ["client_id"])
    op.create_index("ix_website_previews_task_id", "website_previews", ["task_id"])
    op.create_index("ix_website_previews_packet_id", "website_previews", ["packet_id"])
    op.create_index("ix_website_previews_status", "website_previews", ["status"])


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
