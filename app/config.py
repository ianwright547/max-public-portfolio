"""Read Max configuration without storing secrets in source code."""

import os

from dotenv import load_dotenv


# Local development may use a git-ignored .env file. Real hosting platforms
# provide the same names through encrypted environment settings.
load_dotenv(override=False)


def normalize_database_url(database_url: str) -> str:
    """Select Psycopg 3 when a provider supplies a generic PostgreSQL URL."""
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def read_database_url() -> str:
    """Read Max's URL first, then URLs injected by hosting integrations."""
    return normalize_database_url(
        os.getenv("MAX_DATABASE_URL")
        or os.getenv("MAX_DATABASE_DATABASE_URL")
        or os.getenv("POSTGRES_URL")
        or os.getenv("DATABASE_URL")
        or "sqlite:///./max.db"
    )


# Local development uses the short name. Vercel's Neon integration adds the
# second name because its generated `DATABASE_URL` is placed under our
# `MAX_DATABASE` prefix. Supabase's Vercel integration supplies POSTGRES_URL.
DATABASE_URL = read_database_url()
