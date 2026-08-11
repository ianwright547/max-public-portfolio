"""Client-bound Search Console setup and imports without live Google calls."""

from typing import Tuple
from uuid import uuid4

from fastapi.testclient import TestClient

from app.google_search_console_service import (
    GoogleSearchConsoleAdapter,
    SearchConsoleIntegrationError,
    SearchConsoleMetrics,
    SearchConsoleReport,
)
from app.main import app
from tests.test_intakes import make_intake_payload


def client_with_domain(client: TestClient, suffix: str) -> Tuple[str, str]:
    domain = f"{suffix}.example.com"
    created = client.post(
        "/clients",
        json={"business_name": f"Search Console {suffix}", "service_start_date": "2026-08-10"},
    )
    assert created.status_code == 201
    client_id = created.json()["id"]
    intake = make_intake_payload()
    intake["domain"] = domain
    assert client.post(f"/clients/{client_id}/intakes", json=intake).status_code == 201
    return client_id, domain


def test_search_console_property_must_match_the_exact_client_domain() -> None:
    suffix = uuid4().hex[:10]
    with TestClient(app) as client:
        first_id, first_domain = client_with_domain(client, f"first-{suffix}")
        second_id, second_domain = client_with_domain(client, f"second-{suffix}")
        connected = client.post(
            f"/clients/{first_id}/search-console", json={"property_url": f"sc-domain:{first_domain}"}
        )
        wrong_client = client.post(
            f"/clients/{second_id}/search-console", json={"property_url": f"sc-domain:{first_domain}"}
        )
        wrong_domain = client.post(
            f"/clients/{second_id}/search-console", json={"property_url": f"sc-domain:other-{suffix}.example.com"}
        )

    assert connected.status_code == 201
    assert wrong_client.status_code == 409
    assert wrong_client.json()["detail"] == "Search Console property does not match this client domain"
    assert wrong_domain.status_code == 409
    assert second_domain not in connected.json()["property_url"]


def test_search_console_property_requires_a_google_supported_format() -> None:
    suffix = uuid4().hex[:10]
    with TestClient(app) as client:
        client_id, domain = client_with_domain(client, f"format-{suffix}")
        response = client.post(
            f"/clients/{client_id}/search-console", json={"property_url": f"https://{domain}"}
        )

    assert response.status_code == 422
    assert "sc-domain" in response.json()["detail"]


def test_sync_saves_live_historical_metrics_for_correct_client_only(monkeypatch) -> None:
    suffix = uuid4().hex[:10]

    class FakeSearchConsole:
        def read_metrics(self, property_url, start_date, end_date):
            assert property_url == f"sc-domain:sync-{suffix}.example.com"
            assert start_date == "2026-07-01"
            assert end_date == "2026-07-31"
            return SearchConsoleMetrics(clicks=47, impressions=1200)

    with TestClient(app) as client:
        first_id, first_domain = client_with_domain(client, f"sync-{suffix}")
        second_id, _second_domain = client_with_domain(client, f"other-{suffix}")
        assert client.post(
            f"/clients/{first_id}/search-console", json={"property_url": f"sc-domain:{first_domain}"}
        ).status_code == 201
        monkeypatch.setattr("app.routes.search_console.GoogleSearchConsoleAdapter", FakeSearchConsole)
        synced = client.post(
            f"/clients/{first_id}/search-console/sync",
            json={"start_date": "2026-07-01", "end_date": "2026-07-31", "mark_as_baseline": True},
        )
        history = client.get(f"/clients/{first_id}/metrics")
        other_history = client.get(f"/clients/{second_id}/metrics")
        connection = client.get(f"/clients/{first_id}/search-console")

    assert synced.status_code == 200, synced.text
    assert {item["metric_name"] for item in synced.json()} == {"search_clicks", "impressions"}
    assert {item["source_type"] for item in synced.json()} == {"live_api"}
    assert all(item["is_baseline"] for item in synced.json())
    assert {item["client_id"] for item in history.json()} == {first_id}
    assert other_history.json() == []
    assert connection.json()["connection_status"] == "connected"
    assert connection.json()["last_successful_sync_at"] is not None
    assert connection.json()["last_query_rows"] == []
    assert connection.json()["last_page_rows"] == []


def test_sync_persists_bounded_query_and_page_opportunities(monkeypatch) -> None:
    suffix = uuid4().hex[:10]

    class SearchConsoleWithRows:
        def read_report(self, property_url, start_date, end_date):
            assert property_url == f"sc-domain:opportunities-{suffix}.example.com"
            return SearchConsoleReport(
                metrics=SearchConsoleMetrics(clicks=8, impressions=240),
                query_rows=(
                    {"key": "brake repair", "clicks": 0, "impressions": 40, "ctr": 0.0, "position": 8.2},
                ),
                page_rows=(
                    {"key": "https://opportunities.example.com/brakes", "clicks": 8, "impressions": 240, "ctr": 0.033, "position": 7.1},
                ),
            )

    with TestClient(app) as client:
        client_id, domain = client_with_domain(client, f"opportunities-{suffix}")
        assert client.post(
            f"/clients/{client_id}/search-console", json={"property_url": f"sc-domain:{domain}"}
        ).status_code == 201
        monkeypatch.setattr("app.routes.search_console.GoogleSearchConsoleAdapter", SearchConsoleWithRows)
        synced = client.post(
            f"/clients/{client_id}/search-console/sync",
            json={"start_date": "2026-07-01", "end_date": "2026-07-31"},
        )
        connection = client.get(f"/clients/{client_id}/search-console")

    assert synced.status_code == 200
    assert connection.json()["last_query_rows"][0]["key"] == "brake repair"
    assert connection.json()["last_page_rows"][0]["key"].endswith("/brakes")
    assert connection.json()["last_query_start_date"] == "2026-07-01"
    assert connection.json()["last_query_end_date"] == "2026-07-31"


def test_sync_refuses_reversed_dates_and_never_calls_google(monkeypatch) -> None:
    suffix = uuid4().hex[:10]
    with TestClient(app) as client:
        client_id, domain = client_with_domain(client, f"dates-{suffix}")
        assert client.post(
            f"/clients/{client_id}/search-console", json={"property_url": f"sc-domain:{domain}"}
        ).status_code == 201
        monkeypatch.setattr(
            "app.routes.search_console.GoogleSearchConsoleAdapter",
            lambda: (_ for _ in ()).throw(AssertionError("Google should not be called")),
        )
        response = client.post(
            f"/clients/{client_id}/search-console/sync",
            json={"start_date": "2026-08-02", "end_date": "2026-08-01"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "end_date must be on or after start_date"


def test_empty_google_response_is_labeled_not_enough_data_not_zero_metrics(monkeypatch) -> None:
    suffix = uuid4().hex[:10]

    class EmptySearchConsole:
        def read_metrics(self, *_args):
            return SearchConsoleMetrics(clicks=0, impressions=0, has_data=False)

    with TestClient(app) as client:
        client_id, domain = client_with_domain(client, f"empty-{suffix}")
        assert client.post(
            f"/clients/{client_id}/search-console", json={"property_url": f"sc-domain:{domain}"}
        ).status_code == 201
        monkeypatch.setattr("app.routes.search_console.GoogleSearchConsoleAdapter", EmptySearchConsole)
        synced = client.post(
            f"/clients/{client_id}/search-console/sync",
            json={"start_date": "2026-07-01", "end_date": "2026-07-31"},
        )
        metrics = client.get(f"/clients/{client_id}/metrics")
        connection = client.get(f"/clients/{client_id}/search-console")

    assert synced.status_code == 200
    assert synced.json() == []
    assert metrics.json() == []
    assert connection.json()["connection_status"] == "not_enough_data"


def test_search_console_failure_is_carried_into_the_next_report_access_section(monkeypatch) -> None:
    suffix = uuid4().hex[:10]

    class FailingSearchConsole:
        def read_report(self, *_args):
            raise SearchConsoleIntegrationError("search_console_authorization_failed")

    with TestClient(app) as client:
        client_id, domain = client_with_domain(client, f"failure-{suffix}")
        assert client.post(
            f"/clients/{client_id}/search-console", json={"property_url": f"sc-domain:{domain}"}
        ).status_code == 201
        monkeypatch.setattr("app.routes.search_console.GoogleSearchConsoleAdapter", FailingSearchConsole)
        failed = client.post(
            f"/clients/{client_id}/search-console/sync",
            json={"start_date": "2026-07-01", "end_date": "2026-07-31"},
        )
        report = client.post(
            f"/clients/{client_id}/reports",
            json={
                "report_type": "client",
                "period_start": "2026-08-01",
                "period_end": "2026-08-31",
                "generated_by": "Test Owner",
            },
        )

    assert failed.status_code == 502
    access = next(
        item for item in report.json()["snapshot_data"]["access"]
        if item["integration"] == "Google Search Console"
    )
    assert access["status"] == "error"
    assert access["issues"] == ["search_console_authorization_failed"]


def test_adapter_encodes_property_and_returns_aggregate_metrics(monkeypatch) -> None:
    import json

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.body

    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        response = Response()
        response.body = (
            b'{"access_token":"temporary"}'
            if request.full_url == GoogleSearchConsoleAdapter.TOKEN_URL
            else json.dumps({"rows": [{"clicks": 12, "impressions": 345}]}).encode()
        )
        return response

    monkeypatch.setattr("app.google_search_console_service.urlopen", fake_urlopen)
    adapter = GoogleSearchConsoleAdapter("client", "secret", "refresh")
    metrics = adapter.read_metrics("sc-domain:client.example.com", "2026-07-01", "2026-07-31")

    assert metrics == SearchConsoleMetrics(clicks=12, impressions=345, has_data=True)
    assert "%3A" in calls[1].full_url
    assert b"refresh_token=refresh" in calls[0].data


def test_adapter_reads_query_and_page_rows_with_bounded_fields(monkeypatch) -> None:
    import json

    class Response:
        def __init__(self, body):
            self.body = body
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return self.body

    payloads = [
        b'{"access_token":"temporary"}',
        b'{"rows":[{"clicks":12,"impressions":345}]}',
        json.dumps({"rows": [{"keys": ["brake repair"], "clicks": 0, "impressions": 40, "ctr": 0, "position": 8.2}]}).encode(),
        json.dumps({"rows": [{"keys": ["https://example.com/brakes"], "clicks": 12, "impressions": 345, "ctr": 0.034, "position": 7.1}]}).encode(),
    ]
    monkeypatch.setattr(
        "app.google_search_console_service.urlopen",
        lambda _request, timeout: Response(payloads.pop(0)),
    )
    report = GoogleSearchConsoleAdapter("client", "secret", "refresh").read_report(
        "sc-domain:example.com", "2026-07-01", "2026-07-31"
    )

    assert report.metrics == SearchConsoleMetrics(clicks=12, impressions=345)
    assert report.query_rows[0]["key"] == "brake repair"
    assert report.page_rows[0]["position"] == 7.1
