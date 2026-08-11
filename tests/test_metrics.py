"""Phase 5 tests for integrations, metric history, and comparisons."""


def make_metric_client(client, label: str) -> str:
    from uuid import uuid4

    response = client.post(
        "/clients",
        json={
            "business_name": f"{label} {uuid4().hex[:8]}",
            "service_start_date": "2026-08-05",
        },
    )
    return response.json()["id"]


def save_metric(
    client,
    client_id: str,
    metric_name: str,
    value,
    period: str,
    is_baseline: bool = False,
    source_type: str = "manual",
):
    return client.post(
        f"/clients/{client_id}/metrics",
        json={
            "metric_name": metric_name,
            "value": value,
            "measurement_period": period,
            "source_type": source_type,
            "is_baseline": is_baseline,
        },
    )


def test_metric_history_is_preserved_and_comparisons_are_calculated() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        client_id = make_metric_client(client, "History Metrics")
        baseline = save_metric(client, client_id, "calls", 100, "2026-01", True)
        previous = save_metric(client, client_id, "calls", 120, "2026-02")
        current = save_metric(client, client_id, "calls", 150, "2026-03")
        history = client.get(f"/clients/{client_id}/metrics?metric_name=calls")
        comparison = client.get(f"/clients/{client_id}/metrics/calls/comparison")

    assert baseline.status_code == 201
    assert previous.status_code == 201
    assert current.status_code == 201
    assert [snapshot["value"] for snapshot in history.json()] == [100, 120, 150]
    body = comparison.json()
    assert body["baseline"]["id"] == baseline.json()["id"]
    assert body["previous_period"]["id"] == previous.json()["id"]
    assert body["current"]["id"] == current.json()["id"]
    assert body["change_from_baseline"] == {"amount": 50.0, "percent": 50.0, "unit": "value"}
    assert body["change_from_previous"] == {"amount": 30.0, "percent": 25.0, "unit": "value"}


def test_second_baseline_is_rejected_without_changing_the_first() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        client_id = make_metric_client(client, "Baseline Metrics")
        first = save_metric(client, client_id, "reviews", 20, "2026-01", True)
        duplicate = save_metric(client, client_id, "reviews", 30, "2026-02", True)
        history = client.get(f"/clients/{client_id}/metrics?metric_name=reviews")

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "A baseline already exists for reviews"}
    assert len(history.json()) == 1
    assert history.json()[0]["value"] == 20
    assert history.json()[0]["is_baseline"] is True


def test_manual_imported_and_mock_sources_keep_honest_labels() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        client_id = make_metric_client(client, "Source Metrics")
        manual = save_metric(client, client_id, "rating", 4.4, "2026-01", source_type="manual")
        imported = save_metric(client, client_id, "reviews", 44, "2026-01", source_type="imported")
        mock = client.post(
            f"/clients/{client_id}/metrics/mock",
            json={"measurement_period": "2026-02", "mark_as_baseline": False},
        )
        integrations = client.get(f"/clients/{client_id}/integrations")

    assert manual.json()["source_type"] == "manual"
    assert imported.json()["source_type"] == "imported"
    assert len(mock.json()) == 8
    assert {snapshot["source_type"] for snapshot in mock.json()} == {"mock"}
    assert "live_api" not in {record["data_source_type"] for record in integrations.json()}
    mock_connection = next(
        record for record in integrations.json() if record["data_source_type"] == "mock"
    )
    assert mock_connection["connection_status"] == "mock_only"
    assert "not connected" in mock_connection["issues"][0]
    assert mock_connection["last_checked_at"] is not None


def test_invalid_metrics_and_false_live_source_are_rejected() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        client_id = make_metric_client(client, "Invalid Metrics")
        unsupported = save_metric(client, client_id, "revenue", 50, "2026-01")
        negative = save_metric(client, client_id, "calls", -1, "2026-01")
        invalid_rating = save_metric(client, client_id, "rating", 5.5, "2026-01")
        fake_live = save_metric(
            client,
            client_id,
            "calls",
            10,
            "2026-01",
            source_type="live_api",
        )

    assert unsupported.status_code == 422
    assert unsupported.json() == {"detail": "Unsupported metric: revenue"}
    assert negative.status_code == 422
    assert invalid_rating.status_code == 422
    assert fake_live.status_code == 422


def test_metric_history_stays_with_the_correct_client() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        first_client_id = make_metric_client(client, "First Separated Metrics")
        second_client_id = make_metric_client(client, "Second Separated Metrics")
        save_metric(client, first_client_id, "website_clicks", 75, "2026-01")
        save_metric(client, second_client_id, "website_clicks", 900, "2026-01")
        first_history = client.get(
            f"/clients/{first_client_id}/metrics?metric_name=website_clicks"
        )
        second_history = client.get(
            f"/clients/{second_client_id}/metrics?metric_name=website_clicks"
        )

    assert [snapshot["value"] for snapshot in first_history.json()] == [75]
    assert [snapshot["client_id"] for snapshot in first_history.json()] == [first_client_id]
    assert [snapshot["value"] for snapshot in second_history.json()] == [900]
    assert [snapshot["client_id"] for snapshot in second_history.json()] == [second_client_id]


def test_metric_entry_screen_and_unknown_client_behavior() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        client_id = make_metric_client(client, "Visible Metrics")
        page = client.get(f"/dashboard/clients/{client_id}/metrics")
        unknown_page = client.get("/dashboard/clients/client_missing/metrics")
        unknown_metric = client.post(
            "/clients/client_missing/metrics",
            json={
                "metric_name": "calls",
                "value": 10,
                "measurement_period": "2026-01",
                "source_type": "manual",
            },
        )

    assert page.status_code == 200
    assert "Manual entry" in page.text
    assert "Mock data generator" in page.text
    assert "No Google connection" in page.text
    assert "Performance overview" in page.text
    assert "Calls by month" in page.text
    assert unknown_page.status_code == 404
    assert unknown_metric.status_code == 404


def test_manual_screen_actions_save_manual_and_mock_snapshots() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        client_id = make_metric_client(client, "Screen Entry Metrics")
        manual_response = client.post(
            f"/dashboard/clients/{client_id}/metrics/manual",
            data={
                "metric_name": "reviews",
                "value": "31",
                "measurement_period": "2026-01",
                "is_baseline": "on",
            },
            follow_redirects=False,
        )
        mock_response = client.post(
            f"/dashboard/clients/{client_id}/metrics/mock",
            data={"measurement_period": "2026-02"},
            follow_redirects=False,
        )
        history = client.get(f"/clients/{client_id}/metrics")

    assert manual_response.status_code == 303
    assert mock_response.status_code == 303
    assert len(history.json()) == 9
    assert history.json()[0]["source_type"] == "manual"
    assert history.json()[0]["is_baseline"] is True
    assert {snapshot["source_type"] for snapshot in history.json()[1:]} == {"mock"}


def test_metric_dashboard_chart_can_be_customized() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        client_id = make_metric_client(client, "Chart Metrics")
        for period, baseline in (("2026-06", True), ("2026-07", False), ("2026-08", False)):
            client.post(
                f"/clients/{client_id}/metrics/mock",
                json={"measurement_period": period, "mark_as_baseline": baseline},
            )
        page = client.get(
            f"/dashboard/clients/{client_id}/metrics?focus_metric=reviews&periods=3"
        )

    assert page.status_code == 200
    assert "Reviews by month" in page.text
    assert 'aria-label="reviews trend chart"' in page.text
    assert "Last Google post" in page.text
    assert "Chart source: mock" in page.text
    assert page.text.count("<circle") == 3
    assert ">Jun</text>" in page.text
    assert ">Jul</text>" in page.text
    assert ">Aug</text>" in page.text
