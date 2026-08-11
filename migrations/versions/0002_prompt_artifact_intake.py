"""Link onboarding prompt artifacts to their immutable intake."""

from alembic import op
import sqlalchemy as sa


revision = "0002_prompt_artifact_intake"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "prompt_artifacts" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("prompt_artifacts")}
        if "intake_id" not in columns:
            with op.batch_alter_table("prompt_artifacts") as batch:
                batch.add_column(sa.Column("intake_id", sa.String(length=40), nullable=True))
                batch.create_foreign_key("fk_prompt_artifacts_intake_id", "intakes", ["intake_id"], ["id"])


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
