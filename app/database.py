"""Database setup belongs here.

Use this file for engine, session, and table creation code.
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL

IS_SQLITE = DATABASE_URL.startswith("sqlite:")
engine_options = {"connect_args": {"check_same_thread": False}} if IS_SQLITE else {}
engine = create_engine(DATABASE_URL, **engine_options)


if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(database_connection, connection_record) -> None:
        """Make SQLite enforce that child records reference a real client."""
        cursor = database_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autoflush=False, autocommit=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all database models."""


def create_database() -> None:
    """Create all tables registered with the model metadata."""
    from app import models  # noqa: F401

    inspector = inspect(engine)
    if inspector.has_table("clients"):
        column_names = {column["name"] for column in inspector.get_columns("clients")}
        required_columns = {"id", "business_name", "service_start_date", "status", "created_at", "updated_at"}
        if not required_columns.issubset(column_names):
            models.Client.__table__.drop(bind=engine, checkfirst=True)
        elif "archived_at" not in column_names:
            with engine.begin() as connection:
                # TIMESTAMP works in PostgreSQL and SQLite; DATETIME is SQLite-only.
                connection.exec_driver_sql("ALTER TABLE clients ADD COLUMN archived_at TIMESTAMP")
    if inspector.has_table("intakes"):
        column_names = {column["name"] for column in inspector.get_columns("intakes")}
        required_columns = {
            "id",
            "client_id",
            "phone_number",
            "email",
            "brand_colors",
            "domain",
            "business_hours",
            "service_areas",
            "google_business_profile",
            "enabled_workflows",
            "status",
            "submitted_at",
        }
        if not required_columns.issubset(column_names):
            models.Intake.__table__.drop(bind=engine, checkfirst=True)

    # Phase 10 adds resolution time without deleting existing finding history.
    if inspector.has_table("findings"):
        column_names = {column["name"] for column in inspector.get_columns("findings")}
        if "resolved_at" not in column_names:
            with engine.begin() as connection:
                connection.exec_driver_sql("ALTER TABLE findings ADD COLUMN resolved_at DATETIME")

    if inspector.has_table("github_repository_connections"):
        column_names = {
            column["name"] for column in inspector.get_columns("github_repository_connections")
        }
        with engine.begin() as connection:
            if "last_checked_at" not in column_names:
                connection.exec_driver_sql(
                    "ALTER TABLE github_repository_connections ADD COLUMN last_checked_at TIMESTAMP"
                )
            if "last_verified_at" not in column_names:
                connection.exec_driver_sql(
                    "ALTER TABLE github_repository_connections ADD COLUMN last_verified_at TIMESTAMP"
                )

    # Prompt artifacts were added after the initial local database schema.
    # Keep existing SQLite/PostgreSQL development databases readable until
    # the production migration workflow is installed.
    if inspector.has_table("prompt_artifacts"):
        column_names = {column["name"] for column in inspector.get_columns("prompt_artifacts")}
        if "intake_id" not in column_names:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "ALTER TABLE prompt_artifacts ADD COLUMN intake_id VARCHAR(40)"
                )

    if inspector.has_table("reports"):
        column_names = {column["name"] for column in inspector.get_columns("reports")}
        with engine.begin() as connection:
            if "status" not in column_names:
                connection.exec_driver_sql("ALTER TABLE reports ADD COLUMN status VARCHAR(20) DEFAULT 'draft'")
            if "approved_by" not in column_names:
                connection.exec_driver_sql("ALTER TABLE reports ADD COLUMN approved_by VARCHAR(200)")
            if "approved_at" not in column_names:
                connection.exec_driver_sql("ALTER TABLE reports ADD COLUMN approved_at TIMESTAMP")

    Base.metadata.create_all(bind=engine)


def get_database() -> Generator[Session, None, None]:
    """Yield one database session and close it afterward."""
    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()
