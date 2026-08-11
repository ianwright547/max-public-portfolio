"""Allow agency-scoped AI usage without inventing a client association."""

from alembic import op
import sqlalchemy as sa


revision = "0007_agency_ai_usage"
down_revision = "0006_google_oauth_state_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ai_usage_records" not in inspector.get_table_names():
        return
    client_id = next(
        column
        for column in inspector.get_columns("ai_usage_records")
        if column["name"] == "client_id"
    )
    if client_id["nullable"]:
        return
    with op.batch_alter_table("ai_usage_records") as batch:
        batch.alter_column(
            "client_id",
            existing_type=sa.String(length=16),
            nullable=True,
        )


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
