import json
from datetime import date
from uuid import uuid4

from app import models
from app.database import SessionLocal, create_database
from scripts import check_client_provider_health


def test_client_provider_health_script_sweeps_active_clients_and_returns_safe_status(monkeypatch, capsys) -> None:
    create_database()
    with SessionLocal() as database:
        active = models.Client(business_name=f"Health script active {uuid4().hex}", service_start_date=date.today())
        archived = models.Client(business_name=f"Health script archived {uuid4().hex}", service_start_date=date.today(), status="archived")
        database.add_all([active, archived])
        database.commit()
        active_id = active.id

    monkeypatch.setattr(
        check_client_provider_health,
        "verify_client_providers",
        lambda database, client_id: {
            "status": "verified",
            "summary": {"verified": 0, "failed": 0, "probed": 0},
            "results": [],
        },
    )
    assert check_client_provider_health.main(["--client-id", active_id]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "verified"
    assert [item["client_id"] for item in output["clients"]] == [active_id]
    assert "secret" not in json.dumps(output).casefold()
