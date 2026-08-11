"""Phase 6 tests for rules-based client health checks and findings."""


def make_health_client(client, label: str) -> str:
    from uuid import uuid4

    response = client.post(
        "/clients",
        json={"business_name": f"{label} {uuid4().hex[:8]}", "service_start_date": "2026-08-05"},
    )
    return response.json()["id"]


def add_intake(client, client_id: str) -> None:
    client.post(
        f"/clients/{client_id}/intakes",
        json={
            "phone_number": "555-0100",
            "email": "owner@example.com",
            "brand_colors": ["blue"],
            "domain": "https://example.com",
            "business_hours": "Monday-Friday 9-5",
            "service_areas": ["Chicago"],
            "google_business_profile": "Example profile",
            "enabled_workflows": ["website"],
        },
    )


def add_calls(client, client_id: str, first: int, second: int) -> None:
    for period, value in [("2026-06", first), ("2026-07", second)]:
        client.post(
            f"/clients/{client_id}/metrics",
            json={
                "metric_name": "calls",
                "value": value,
                "measurement_period": period,
                "source_type": "manual",
            },
        )


def test_healthy_client_has_no_unnecessary_finding() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "Healthy Check")
        add_intake(client, client_id)
        add_calls(client, client_id, 100, 105)
        response = client.post(
            f"/clients/{client_id}/health-checks", json={"website_status": "available"}
        )

    assert response.status_code == 201
    assert response.json()["overall_status"] == "healthy"
    assert response.json()["findings"] == []
    assert "No action is needed" in response.json()["summary"]


def test_unavailable_website_is_critical_and_has_evidence() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "Critical Check")
        add_intake(client, client_id)
        add_calls(client, client_id, 10, 11)
        response = client.post(
            f"/clients/{client_id}/health-checks", json={"website_status": "unavailable"}
        )

    body = response.json()
    finding = next(item for item in body["findings"] if item["title"] == "Website unavailable")
    assert body["overall_status"] == "critical"
    assert finding["severity"] == "critical"
    assert finding["evidence"] == {
        "domain": "https://example.com",
        "observed_status": "unavailable",
    }
    assert finding["source"] == "manual_website_check"
    assert finding["recommended_action"]


def test_major_metric_decline_is_explained_without_claiming_a_cause() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "Decline Check")
        add_intake(client, client_id)
        add_calls(client, client_id, 100, 60)
        response = client.post(
            f"/clients/{client_id}/health-checks", json={"website_status": "available"}
        )

    finding = response.json()["findings"][0]
    assert response.json()["overall_status"] == "needs_attention"
    assert finding["title"] == "Calls declined"
    assert finding["evidence"]["percent_change"] == -40.0
    assert "not its cause" in finding["explanation"]


def test_missing_data_returns_not_enough_data() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "Missing Check")
        response = client.post(
            f"/clients/{client_id}/health-checks", json={"website_status": "unknown"}
        )

    assert response.json()["overall_status"] == "not_enough_data"
    evidence = response.json()["findings"][0]["evidence"]["missing"]
    assert "No onboarding intake is saved" in evidence
    assert "Website availability has not been checked" in evidence
    assert "No metric has two comparable periods" in evidence


def test_repeated_unresolved_issue_refreshes_one_finding_and_preserves_observations() -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app import models
    from app.database import SessionLocal
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "Repeat Check")
        add_intake(client, client_id)
        add_calls(client, client_id, 10, 11)
        first = client.post(
            f"/clients/{client_id}/health-checks", json={"website_status": "unavailable"}
        )
        second = client.post(
            f"/clients/{client_id}/health-checks", json={"website_status": "unavailable"}
        )
        findings = client.get(f"/clients/{client_id}/findings")

    first_finding = next(item for item in first.json()["findings"] if item["title"] == "Website unavailable")
    second_finding = next(item for item in second.json()["findings"] if item["title"] == "Website unavailable")
    matching = [item for item in findings.json() if item["title"] == "Website unavailable"]
    assert first_finding["id"] == second_finding["id"]
    assert len(matching) == 1
    assert matching[0]["occurrence_count"] == 2

    with SessionLocal() as database:
        observations = list(
            database.scalars(
                select(models.FindingObservation).where(
                    models.FindingObservation.client_id == client_id,
                    models.FindingObservation.finding_id == first_finding["id"],
                )
            )
        )
    assert len(observations) == 2
    assert observations[0].evidence == observations[1].evidence


def test_health_records_never_cross_clients() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        critical_id = make_health_client(client, "Separated Critical")
        healthy_id = make_health_client(client, "Separated Healthy")
        for client_id in [critical_id, healthy_id]:
            add_intake(client, client_id)
            add_calls(client, client_id, 10, 11)
        client.post(
            f"/clients/{critical_id}/health-checks", json={"website_status": "unavailable"}
        )
        client.post(
            f"/clients/{healthy_id}/health-checks", json={"website_status": "available"}
        )
        critical_findings = client.get(f"/clients/{critical_id}/findings")
        healthy_findings = client.get(f"/clients/{healthy_id}/findings")

    assert {item["client_id"] for item in critical_findings.json()} == {critical_id}
    assert healthy_findings.json() == []


def test_unknown_client_is_rejected_and_demo_page_is_visible() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "Visible Check")
        page = client.get(f"/dashboard/clients/{client_id}/health")
        unknown = client.post(
            "/clients/client_missing/health-checks", json={"website_status": "available"}
        )

    assert page.status_code == 200
    assert "Run a check" in page.text
    assert "will not contact the website or create work" in page.text
    assert unknown.status_code == 404


def test_demo_form_runs_a_check_without_optional_form_dependency() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client_id = make_health_client(client, "Form Check")
        response = client.post(
            f"/dashboard/clients/{client_id}/health/run",
            data={"website_status": "unavailable"},
            follow_redirects=False,
        )
        findings = client.get(f"/clients/{client_id}/findings")

    assert response.status_code == 303
    assert response.headers["location"].endswith("/health?saved=1")
    assert any(item["title"] == "Website unavailable" for item in findings.json())
