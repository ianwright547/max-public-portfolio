"""Add human content review records for Codex local-page and blog work."""

from alembic import op
import sqlalchemy as sa


revision = "0024_content_reviews"
down_revision = "0023_agency_members"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "content_reviews" in inspector.get_table_names():
        return
    op.create_table(
        "content_reviews",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("client_id", sa.String(length=16), nullable=False),
        sa.Column("task_id", sa.String(length=24), nullable=False),
        sa.Column("packet_id", sa.String(length=28), nullable=False),
        sa.Column("execution_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("reviewer", sa.String(length=200), nullable=True),
        sa.Column("checklist", sa.JSON(), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["packet_id"], ["codex_work_packets.id"]),
        sa.ForeignKeyConstraint(["execution_id"], ["fulfillment_executions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("packet_id"),
    )
    op.create_index("ix_content_reviews_client_id", "content_reviews", ["client_id"])
    op.create_index("ix_content_reviews_task_id", "content_reviews", ["task_id"])
    op.create_index("ix_content_reviews_packet_id", "content_reviews", ["packet_id"], unique=True)
    op.create_index("ix_content_reviews_execution_id", "content_reviews", ["execution_id"])
    op.create_index("ix_content_reviews_status", "content_reviews", ["status"])


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
