"""Track Codex packet handoff and returned execution evidence."""

from alembic import op
import sqlalchemy as sa


revision = "0011_codex_handoff_lifecycle"
down_revision = "0010_daily_client_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("codex_work_packets")}
    with op.batch_alter_table("codex_work_packets") as batch:
        if "handed_off_by" not in columns:
            batch.add_column(sa.Column("handed_off_by", sa.String(length=200), nullable=True))
        if "handed_off_at" not in columns:
            batch.add_column(sa.Column("handed_off_at", sa.DateTime(), nullable=True))
            batch.create_index("ix_codex_work_packets_handed_off_at", ["handed_off_at"])
        if "result_execution_id" not in columns:
            batch.add_column(sa.Column("result_execution_id", sa.String(length=32), nullable=True))
            batch.create_index("ix_codex_work_packets_result_execution_id", ["result_execution_id"], unique=True)
            batch.create_foreign_key(
                "fk_codex_work_packets_result_execution_id",
                "fulfillment_executions",
                ["result_execution_id"],
                ["id"],
            )


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
