"""The public demo must stay readable, immutable, and impossible to enable by accident."""

import pytest

from app import demo_mode


def test_demo_mode_is_off_unless_explicitly_requested(monkeypatch) -> None:
    monkeypatch.delenv("MAX_PUBLIC_DEMO", raising=False)
    assert demo_mode.demo_mode_enabled() is False


def test_demo_mode_never_overrides_configured_owner_auth(monkeypatch) -> None:
    """A private deployment must not fall open because the flag got set."""
    monkeypatch.setenv("MAX_PUBLIC_DEMO", "1")
    monkeypatch.setenv("AUTH_SECRET", "secret-value")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://max.example/google/oauth/callback")
    monkeypatch.setenv("MAX_ALLOWED_GOOGLE_EMAILS", "owner@example.com")

    assert demo_mode.demo_mode_requested() is True
    assert demo_mode.demo_mode_enabled() is False


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/clients"),
        ("PATCH", "/clients/demo-cl-0001"),
        ("DELETE", "/clients/demo-cl-0001"),
        ("POST", "/dashboard/agency/members"),
        ("POST", "/reports"),
    ],
)
def test_demo_refuses_every_state_changing_request(monkeypatch, tmp_path, method, path) -> None:
    monkeypatch.setenv("MAX_PUBLIC_DEMO", "1")
    monkeypatch.setenv("MAX_DATABASE_URL", f"sqlite:///{tmp_path/'demo.db'}")
    for name in (
        "AUTH_SECRET",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "MAX_ALLOWED_GOOGLE_EMAILS",
    ):
        monkeypatch.delenv(name, raising=False)

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.request(method, path, json={})

    assert response.status_code == 403
    assert response.json()["detail"] == "demo_is_read_only"


def test_demo_seed_is_idempotent(tmp_path) -> None:
    """A warm serverless instance must not duplicate the portfolio."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app import models
    from app.database import Base
    from app.demo_data import seed_demo_data

    engine = create_engine(f"sqlite:///{tmp_path/'seed.db'}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    with Session() as database:
        first = seed_demo_data(database)
    with Session() as database:
        second = seed_demo_data(database)
        total = len(list(database.scalars(select(models.Client))))

    assert first > 0
    assert second == 0
    assert total == first
