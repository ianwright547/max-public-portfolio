"""Add scheduler leases, failure counters, and duration telemetry."""

from alembic import op
import sqlalchemy as sa


revision = "0012_scheduled_job_leases"
down_revision = "0011_codex_handoff_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("scheduled_jobs")}
    with op.batch_alter_table("scheduled_jobs") as batch:
        if "last_started_at" not in columns:
            batch.add_column(sa.Column("last_started_at", sa.DateTime(), nullable=True))
        if "consecutive_failures" not in columns:
            batch.add_column(sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"))
        if "last_duration_seconds" not in columns:
            batch.add_column(sa.Column("last_duration_seconds", sa.Float(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
