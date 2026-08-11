"""Persist post-fulfillment outcome measurements."""

from alembic import op
import sqlalchemy as sa


revision = "0022_outcome_measurements"
down_revision = "0021_task_acceptance_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "outcome_measurements" in inspector.get_table_names():
        return
    op.create_table(
        "outcome_measurements",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("operation_key", sa.String(length=120), nullable=False),
        sa.Column("client_id", sa.String(length=16), nullable=False),
        sa.Column("task_id", sa.String(length=24), nullable=False),
        sa.Column("execution_id", sa.String(length=32), nullable=True),
        sa.Column("metric_name", sa.String(length=200), nullable=False),
        sa.Column("baseline_value", sa.Float(), nullable=True),
        sa.Column("observed_value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=80), nullable=True),
        sa.Column("assessment", sa.String(length=20), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("notes", sa.String(length=1200), nullable=False),
        sa.Column("recorded_by", sa.String(length=200), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["execution_id"], ["fulfillment_executions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_key"),
    )
    op.create_index("ix_outcome_measurements_operation_key", "outcome_measurements", ["operation_key"], unique=True)
    op.create_index("ix_outcome_measurements_client_id", "outcome_measurements", ["client_id"])
    op.create_index("ix_outcome_measurements_task_id", "outcome_measurements", ["task_id"])
    op.create_index("ix_outcome_measurements_execution_id", "outcome_measurements", ["execution_id"])


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
