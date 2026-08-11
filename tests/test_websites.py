"""Tests for verified client-to-Vercel website links."""


def make_website_client(client, label: str) -> str:
    from uuid import uuid4

    response = client.post(
        "/clients",
        json={
            "business_name": f"{label} {uuid4().hex[:8]}",
            "service_start_date": "2026-06-01",
        },
    )
    return response.json()["id"]


def website_payload(suffix: str) -> dict:
    return {
        "provider": "vercel",
        "external_project_id": f"prj_{suffix}",
        "project_name": f"client-site-{suffix}",
        "production_url": f"https://{suffix}.example.com",
        "source": "vercel_cli",
    }


def test_link_and_retrieve_verified_website() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_website_client(client, "Website Link")
        created = client.post(
            f"/clients/{client_id}/website-connection", json=website_payload(client_id)
        )
        retrieved = client.get(f"/clients/{client_id}/website-connection")

    assert created.status_code == 201
    assert retrieved.json()["client_id"] == client_id
    assert retrieved.json()["connection_status"] == "linked"
    assert retrieved.json()["source"] == "vercel_cli"


def test_website_or_project_cannot_be_linked_twice() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        first_id = make_website_client(client, "First Website")
        second_id = make_website_client(client, "Second Website")
        payload = website_payload(first_id)
        first = client.post(f"/clients/{first_id}/website-connection", json=payload)
        duplicate_client = client.post(
            f"/clients/{first_id}/website-connection", json=website_payload(second_id)
        )
        duplicate_project = client.post(
            f"/clients/{second_id}/website-connection", json=payload
        )

    assert first.status_code == 201
    assert duplicate_client.status_code == 409
    assert duplicate_project.status_code == 409


def test_website_links_remain_separated_and_visible_on_dashboard() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        linked_id = make_website_client(client, "Linked Website")
        unlinked_id = make_website_client(client, "Unlinked Website")
        payload = website_payload(linked_id)
        client.post(f"/clients/{linked_id}/website-connection", json=payload)
        page = client.get("/dashboard")
        unlinked = client.get(f"/clients/{unlinked_id}/website-connection")

    linked_start = page.text.index(f'data-client-id="{linked_id}"')
    linked_end = page.text.index("</article>", linked_start)
    unlinked_start = page.text.index(f'data-client-id="{unlinked_id}"')
    unlinked_end = page.text.index("</article>", unlinked_start)
    assert payload["production_url"] in page.text[linked_start:linked_end]
    assert payload["production_url"] not in page.text[unlinked_start:unlinked_end]
    assert unlinked.status_code == 404


def test_unknown_client_cannot_receive_website_link() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        response = client.post(
            "/clients/client_missing/website-connection",
            json=website_payload("missing"),
        )

    assert response.status_code == 404


def test_dashboard_can_show_only_clients_with_linked_websites() -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app import models
    from app.database import SessionLocal
    from app.main import app

    with TestClient(app) as client:
        linked_id = make_website_client(client, "Filtered Linked")
        unlinked_id = make_website_client(client, "Filtered Unlinked")
        client.post(
            f"/clients/{linked_id}/website-connection",
            json=website_payload(linked_id),
        )

        # Only the authenticated importer may apply this confirmed-source label.
        with SessionLocal() as database:
            connection = database.scalar(
                select(models.WebsiteConnection).where(
                    models.WebsiteConnection.client_id == linked_id
                )
            )
            connection.source = "confirmed_vercel_import"
            database.commit()

        page = client.get("/dashboard?linked_only=true")

    assert f'data-client-id="{linked_id}"' in page.text
    assert f'data-client-id="{unlinked_id}"' not in page.text
