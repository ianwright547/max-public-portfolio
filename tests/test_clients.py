def test_create_client() -> None:
    from fastapi.testclient import TestClient
    from uuid import uuid4

    from app.main import app

    business_name = f"Example Business {uuid4().hex[:8]}"

    with TestClient(app) as client:
        response = client.post(
            "/clients",
            json={
                "business_name": business_name,
                "service_start_date": "2026-08-05",
            },
        )

    assert response.status_code == 201

    body = response.json()
    assert body["business_name"] == business_name
    assert body["service_start_date"] == "2026-08-05"
    assert body["status"] == "onboarding"
    assert body["id"].startswith("client_")


def test_list_clients() -> None:
    from fastapi.testclient import TestClient
    from uuid import uuid4

    from app.main import app

    first_name = f"First Client {uuid4().hex[:8]}"
    second_name = f"Second Client {uuid4().hex[:8]}"

    with TestClient(app) as client:
        first_response = client.post(
            "/clients",
            json={"business_name": first_name, "service_start_date": "2026-08-05"},
        )
        second_response = client.post(
            "/clients",
            json={"business_name": second_name, "service_start_date": "2026-08-06"},
        )
        list_response = client.get("/clients")

    saved_ids = {client_record["id"] for client_record in list_response.json()}
    assert first_response.json()["id"] in saved_ids
    assert second_response.json()["id"] in saved_ids


def test_read_one_client() -> None:
    from fastapi.testclient import TestClient
    from uuid import uuid4

    from app.main import app

    business_name = f"Readable Client {uuid4().hex[:8]}"

    with TestClient(app) as client:
        create_response = client.post(
            "/clients",
            json={"business_name": business_name, "service_start_date": "2026-08-05"},
        )
        client_id = create_response.json()["id"]
        read_response = client.get(f"/clients/{client_id}")

    assert read_response.status_code == 200
    assert read_response.json()["id"] == client_id
    assert read_response.json()["business_name"] == business_name


def test_read_unknown_client_returns_error() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/clients/client_missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Client not found"}


def test_create_client_rejects_duplicate_business_name() -> None:
    from fastapi.testclient import TestClient
    from uuid import uuid4

    from app.main import app

    business_name = f"Duplicate Business {uuid4().hex[:8]}"
    payload = {
        "business_name": business_name,
        "service_start_date": "2026-08-05",
    }

    with TestClient(app) as client:
        first_response = client.post("/clients", json=payload)
        second_response = client.post("/clients", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert second_response.json() == {"detail": "Client already exists"}


def test_create_client_rejects_missing_required_information() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.post("/clients", json={"business_name": ""})

    assert response.status_code == 422


def test_client_remains_saved_after_new_test_client() -> None:
    from fastapi.testclient import TestClient
    from uuid import uuid4

    from app.main import app

    business_name = f"Persistent Client {uuid4().hex[:8]}"

    with TestClient(app) as client:
        create_response = client.post(
            "/clients",
            json={"business_name": business_name, "service_start_date": "2026-08-05"},
        )
        client_id = create_response.json()["id"]

    with TestClient(app) as client:
        read_response = client.get(f"/clients/{client_id}")

    assert read_response.status_code == 200
    assert read_response.json()["business_name"] == business_name


def test_client_can_be_updated_without_changing_id() -> None:
    from fastapi.testclient import TestClient
    from uuid import uuid4
    from app.main import app

    with TestClient(app) as client:
        created = client.post(
            "/clients",
            json={"business_name": f"Editable {uuid4().hex[:8]}", "service_start_date": "2026-08-05"},
        ).json()
        updated = client.patch(
            f"/clients/{created['id']}",
            json={"business_name": "Updated Business", "service_start_date": "2026-08-06"},
        )

    assert updated.status_code == 200
    assert updated.json()["id"] == created["id"]
    assert updated.json()["business_name"] == "Updated Business"
    assert updated.json()["service_start_date"] == "2026-08-06"


def test_archiving_hides_client_but_preserves_history() -> None:
    from fastapi.testclient import TestClient
    from uuid import uuid4
    from app.main import app

    with TestClient(app) as client:
        created = client.post(
            "/clients",
            json={"business_name": f"Archivable {uuid4().hex[:8]}", "service_start_date": "2026-08-05"},
        ).json()
        archived = client.post(f"/clients/{created['id']}/archive")
        active = client.get("/clients")
        history = client.get("/clients?include_archived=true")

    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert archived.json()["archived_at"] is not None
    assert created["id"] not in {item["id"] for item in active.json()}
    assert created["id"] in {item["id"] for item in history.json()}


def test_delete_client_removes_it_from_active_operations_but_preserves_history() -> None:
    from fastapi.testclient import TestClient
    from uuid import uuid4
    from app.main import app

    with TestClient(app) as client:
        created = client.post(
            "/clients",
            json={"business_name": f"Deletable {uuid4().hex[:8]}", "service_start_date": "2026-08-05"},
        ).json()
        removed = client.delete(f"/clients/{created['id']}")
        active = client.get("/clients")
        history = client.get("/clients?include_archived=true")

    assert removed.status_code == 200
    assert removed.json()["status"] == "archived"
    assert created["id"] not in {item["id"] for item in active.json()}
    assert created["id"] in {item["id"] for item in history.json()}


def test_archiving_disables_all_future_client_jobs_and_blocks_new_work() -> None:
    from fastapi.testclient import TestClient
    from uuid import uuid4
    from app.main import app
    from app.database import SessionLocal
    from app import models
    from sqlalchemy import select

    with TestClient(app) as client:
        created = client.post(
            "/clients",
            json={"business_name": f"Cleanup {uuid4().hex[:8]}", "service_start_date": "2026-08-05"},
        ).json()
        job = client.post(
            "/jobs",
            json={
                "job_key": f"cleanup-health-{uuid4().hex[:8]}",
                "job_type": "health_check",
                "client_id": created["id"],
                "interval_minutes": 60,
            },
        )
        archived = client.post(f"/clients/{created['id']}/archive")
        report = client.post(
            f"/clients/{created['id']}/reports",
            json={
                "report_type": "internal",
                "period_start": "2026-08-01",
                "period_end": "2026-08-31",
                "generated_by": "Agency Owner",
            },
        )

    assert job.status_code == 201
    assert archived.status_code == 200
    assert report.status_code == 409
    with SessionLocal() as database:
        saved_job = database.scalar(
            select(models.ScheduledJob).where(models.ScheduledJob.id == job.json()["id"])
        )
    assert saved_job.enabled is False


def test_update_rejects_duplicate_business_name_case_insensitively() -> None:
    from fastapi.testclient import TestClient
    from uuid import uuid4
    from app.main import app

    with TestClient(app) as client:
        first = client.post(
            "/clients",
            json={"business_name": f"First {uuid4().hex[:8]}", "service_start_date": "2026-08-05"},
        ).json()
        second_name = f"Second {uuid4().hex[:8]}"
        client.post(
            "/clients",
            json={"business_name": second_name, "service_start_date": "2026-08-05"},
        )
        response = client.patch(f"/clients/{first['id']}", json={"business_name": second_name.lower()})

    assert response.status_code == 409
