"""Configuration tests protect local SQLite and hosted PostgreSQL modes."""

from app.config import normalize_database_url, read_database_url


def test_sqlite_url_remains_unchanged() -> None:
    assert normalize_database_url("sqlite:///./max.db") == "sqlite:///./max.db"


def test_generic_postgresql_url_uses_psycopg_three() -> None:
    assert (
        normalize_database_url("postgresql://user:secret@example.test/max")
        == "postgresql+psycopg://user:secret@example.test/max"
    )


def test_legacy_postgres_url_uses_psycopg_three() -> None:
    assert (
        normalize_database_url("postgres://user:secret@example.test/max")
        == "postgresql+psycopg://user:secret@example.test/max"
    )


def test_vercel_neon_database_url_is_supported(monkeypatch) -> None:
    monkeypatch.delenv("MAX_DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MAX_DATABASE_DATABASE_URL",
        "postgresql://user:secret@example.test/max",
    )

    assert (
        read_database_url()
        == "postgresql+psycopg://user:secret@example.test/max"
    )


def test_local_database_url_wins_over_vercel_name(monkeypatch) -> None:
    monkeypatch.setenv("MAX_DATABASE_URL", "sqlite:///./local.db")
    monkeypatch.setenv(
        "MAX_DATABASE_DATABASE_URL",
        "postgresql://user:secret@example.test/max",
    )

    assert read_database_url() == "sqlite:///./local.db"


def test_supabase_vercel_postgres_url_is_supported(monkeypatch) -> None:
    monkeypatch.delenv("MAX_DATABASE_URL", raising=False)
    monkeypatch.delenv("MAX_DATABASE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "POSTGRES_URL",
        "postgres://postgres.example:secret@pooler.example.test:6543/postgres",
    )

    assert read_database_url() == (
        "postgresql+psycopg://postgres.example:secret@pooler.example.test:6543/postgres"
    )
