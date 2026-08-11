"""Add measurable acceptance fields to proposed tasks."""

from alembic import op
import sqlalchemy as sa


revision = "0021_task_acceptance_contract"
down_revision = "0020_report_share_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("tasks")}
    additions = (
        (
            "expected_result",
            sa.String(length=1200),
            "Verify the requested outcome with source evidence.",
        ),
        (
            "success_metric",
            sa.String(length=500),
            "The source-specific metric named in the evidence.",
        ),
        (
            "verification_window",
            sa.String(length=300),
            "Verify in the next reporting cycle.",
        ),
    )
    missing = [item for item in additions if item[0] not in existing]
    if missing:
        with op.batch_alter_table("tasks") as batch:
            for name, type_, default in missing:
                batch.add_column(
                    sa.Column(name, type_, nullable=False, server_default=default)
                )


def downgrade() -> None:
    op.drop_column("tasks", "verification_window")
    op.drop_column("tasks", "success_metric")
    op.drop_column("tasks", "expected_result")
