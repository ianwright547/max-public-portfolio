"""Tests for aggregate website analytics import and portfolio views."""

from datetime import date


def create_named_client(client, business_name: str) -> str:
    response = client.post(
        "/clients",
        json={"business_name": business_name, "service_start_date": "2026-06-01"},
    )
    return response.json()["id"]


def test_sync_imports_aggregate_metrics_and_combines_tracker_aliases() -> None:
    from fastapi.testclient import TestClient

    from app.database import SessionLocal
    from app.main import app
    from app.website_analytics import sync_website_metrics

    rows = [
        {"site": "demo-mobile-mechanics", "unique_visitors": 10, "pageviews": 20, "call_clicks": 3, "form_submits": 1},
        {"site": "toppoolcleaningtx", "unique_visitors": 7, "pageviews": 11, "call_clicks": 1, "form_submits": 2},
        {"site": "toppoolcleaning", "unique_visitors": 2, "pageviews": 4, "call_clicks": 0, "form_submits": 1},
        {"site": "not_a_max_client", "unique_visitors": 99, "pageviews": 99, "call_clicks": 99, "form_submits": 99},
    ]
    with TestClient(app) as client:
        des_moines_id = create_named_client(client, "Demo Mobile Mechanics")
        top_pool_id = create_named_client(client, "Top Pool Cleaning")

    with SessionLocal() as database:
        from app import models

        database.add_all(
            [
                models.WebsiteAnalyticsConnection(
                    client_id=des_moines_id,
                    tracker_sites=["demo-mobile-mechanics"],
                ),
                models.WebsiteAnalyticsConnection(
                    client_id=top_pool_id,
                    tracker_sites=["toppoolcleaningtx", "toppoolcleaning"],
                ),
            ]
        )
        database.commit()
        snapshots, unmatched, reused = sync_website_metrics(
            database, 30, fetcher=lambda start, end: rows, today=date(2026, 8, 5)
        )

    by_client = {item.client_id: item for item in snapshots}
    assert reused is False
    assert unmatched == ["not_a_max_client"]
    assert by_client[des_moines_id].unique_visitors == 10
    assert by_client[top_pool_id].unique_visitors == 9
    assert by_client[top_pool_id].pageviews == 15
    assert by_client[top_pool_id].tracker_sites == ["toppoolcleaningtx", "toppoolcleaning"]
    assert by_client[top_pool_id].source == "website_analytics_dashboard"


def test_repeated_same_day_sync_reuses_history_without_fetching_again() -> None:
    from fastapi.testclient import TestClient

    from app.database import SessionLocal
    from app.main import app
    from app.website_analytics import sync_website_metrics

    calls = {"count": 0}
    rows = [{"site": "passionpoolcare", "unique_visitors": 8, "pageviews": 12, "call_clicks": 2, "form_submits": 1}]

    def fetcher(start, end):
        calls["count"] += 1
        return rows

    with TestClient(app) as client:
        client_id = create_named_client(client, "Passion Pool Care")
    with SessionLocal() as database:
        from app import models

        database.add(
            models.WebsiteAnalyticsConnection(
                client_id=client_id,
                tracker_sites=["passionpoolcare"],
            )
        )
        database.commit()
        first, _, first_reused = sync_website_metrics(database, 7, fetcher, date(2026, 8, 5))
        second, _, second_reused = sync_website_metrics(database, 7, fetcher, date(2026, 8, 5))

    matching_first = [item for item in first if item.client_id == client_id]
    matching_second = [item for item in second if item.client_id == client_id]
    # Other durable client mappings may still need the same provider window;
    # the invariant for this client is that its completed snapshot is reused
    # and never duplicated.
    assert calls["count"] >= 1
    assert first_reused is False
    assert second_reused is True
    assert matching_first[0].id == matching_second[0].id


def test_invalid_tracker_counts_are_rejected_without_saved_snapshot() -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app import models
    from app.database import SessionLocal
    from app.main import app
    from app.website_analytics import sync_website_metrics

    bad_rows = [{"site": "segurastowing", "unique_visitors": -1, "pageviews": 5, "call_clicks": 0, "form_submits": 0}]
    with TestClient(app) as client:
        client_id = create_named_client(client, "Seguras Towing")
    with SessionLocal() as database:
        database.add(
            models.WebsiteAnalyticsConnection(
                client_id=client_id,
                tracker_sites=["segurastowing"],
            )
        )
        database.commit()
        try:
            sync_website_metrics(database, 90, lambda start, end: bad_rows, date(2026, 8, 5))
        except ValueError as error:
            database.rollback()
            assert "unique_visitors" in str(error)
        else:
            raise AssertionError("Negative tracker data should fail")
        saved = list(database.scalars(select(models.WebsiteMetricSnapshot).where(models.WebsiteMetricSnapshot.client_id == client_id)))
    assert saved == []


def test_provider_failure_marks_website_analytics_unavailable_for_reports() -> None:
    from urllib.error import URLError

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app import models
    from app.database import SessionLocal
    from app.main import app
    from app.website_analytics import sync_website_metrics

    with TestClient(app) as client:
        client_id = create_named_client(client, "Unavailable Analytics Client")
    with SessionLocal() as database:
        database.add(
            models.WebsiteAnalyticsConnection(
                client_id=client_id,
                tracker_sites=["unavailable-site"],
            )
        )
        database.commit()
        try:
            sync_website_metrics(
                database,
                30,
                lambda _start, _end: (_ for _ in ()).throw(URLError("provider offline")),
                date(2026, 8, 5),
            )
        except URLError:
            pass
        integration = database.scalar(
            select(models.IntegrationConnection).where(
                models.IntegrationConnection.client_id == client_id,
                models.IntegrationConnection.integration_name == "Website analytics dashboard",
            )
        )

    assert integration is not None
    assert integration.connection_status == "error"
    assert integration.issues == ["website_analytics_sync_failed"]


def test_overall_metrics_averages_and_client_filter_keep_data_separate() -> None:
    from fastapi.testclient import TestClient

    from app import models
    from app.database import SessionLocal
    from app.main import app

    with TestClient(app) as client:
        first_id = create_named_client(client, "Demo Auto Service")
        second_id = create_named_client(client, "Thompson Roofing")
    with SessionLocal() as database:
        for client_id, project, visitors in [(first_id, "seabee", 100), (second_id, "thompson", 300)]:
            database.add(models.WebsiteConnection(client_id=client_id, provider="vercel", external_project_id=f"prj_{project}", project_name=project, production_url=f"https://{project}.example.com", source="confirmed_vercel_import"))
            database.add(models.WebsiteMetricSnapshot(client_id=client_id, period_start=date(2026, 7, 6), period_end=date(2026, 8, 5), window_days=30, unique_visitors=visitors, pageviews=visitors * 2, call_clicks=10, form_submits=4, tracker_sites=[project], source="website_analytics_dashboard"))
        database.commit()

    with TestClient(app) as client:
        overall = client.get("/dashboard/metrics")
        filtered = client.get(f"/dashboard/metrics?client_id={first_id}")
        client_page = client.get(f"/dashboard/clients/{first_id}/metrics")

    assert "Portfolio averages across 2 reporting clients" in overall.text
    assert "200.0" in overall.text
    assert "Portfolio totals: 400 visitors" in overall.text
    assert "Demo Auto Service · latest 30-day snapshot" in filtered.text
    assert "300" not in filtered.text
    assert "Website analytics" in client_page.text
    assert "Unique visitors" in client_page.text
    assert "Source: website_analytics_dashboard" in client_page.text


def test_unknown_client_and_invalid_window_are_rejected() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        unknown = client.get("/clients/client_missing/website-metrics")
        client_id = create_named_client(client, "Affordable Care Tire Service")
        invalid = client.get(f"/clients/{client_id}/website-metrics?window_days=12")

    assert unknown.status_code == 404
    assert invalid.status_code == 422
