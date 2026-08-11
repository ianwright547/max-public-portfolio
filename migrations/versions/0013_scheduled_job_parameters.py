"""Persist configuration for recurring planning and reporting jobs."""

from alembic import op
import sqlalchemy as sa


revision = "0013_scheduled_job_parameters"
down_revision = "0012_scheduled_job_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("scheduled_jobs")}
    with op.batch_alter_table("scheduled_jobs") as batch:
        if "parameters" not in columns:
            batch.add_column(sa.Column("parameters", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
