"""Add owner-login context to legacy Google OAuth state records."""

from alembic import op
import sqlalchemy as sa


revision = "0006_google_oauth_state_context"
down_revision = "0005_report_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "google_oauth_states" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("google_oauth_states")}
    with op.batch_alter_table("google_oauth_states") as batch:
        if "purpose" not in columns:
            batch.add_column(
                sa.Column(
                    "purpose",
                    sa.String(length=40),
                    nullable=False,
                    server_default="integration_setup",
                )
            )
        if "nonce_hash" not in columns:
            batch.add_column(sa.Column("nonce_hash", sa.String(length=128), nullable=True))
        if "redirect_path" not in columns:
            batch.add_column(sa.Column("redirect_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
