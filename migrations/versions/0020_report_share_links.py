"""Add expiring and revocable client report share-link state."""

from alembic import op
import sqlalchemy as sa


revision = "0020_report_share_links"
down_revision = "0019_search_console_opportunity_rows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("reports")}
    additions = {
        "client_share_issued_at": sa.Column("client_share_issued_at", sa.DateTime(), nullable=True),
        "client_share_revoked_at": sa.Column("client_share_revoked_at", sa.DateTime(), nullable=True),
    }
    if any(name not in columns for name in additions):
        with op.batch_alter_table("reports") as batch:
            for name, column in additions.items():
                if name not in columns:
                    batch.add_column(column)


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
