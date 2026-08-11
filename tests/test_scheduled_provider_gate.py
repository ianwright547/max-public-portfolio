from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import select

from app import models
from app.database import SessionLocal, create_database
from app import job_service


def test_scheduled_fulfillment_plan_fails_closed_after_provider_probe(monkeypatch) -> None:
    create_database()
    calls = []

    def failed_probe(database, client_id):
        calls.append(client_id)
        return {
            "status": "failed",
            "results": [{"provider": "slack", "status": "failed", "code": "slack_workspace_mismatch"}],
            "summary": {"verified": 0, "failed": 1, "probed": 1},
        }

    monkeypatch.setattr("app.client_provider_verification.verify_client_providers", failed_probe)
    with SessionLocal() as database:
        client = models.Client(business_name=f"Scheduled provider gate {uuid4().hex}", service_start_date=date.today())
        database.add(client)
        database.flush()
        client_id = client.id
        job = models.ScheduledJob(
            job_key=f"provider-gate:{uuid4().hex}",
            job_type="daily_client_plan",
            client_id=client.id,
            interval_minutes=1440,
            next_run_at=datetime.utcnow(),
            parameters={"focus": "fulfillment", "create_tasks": True},
        )
        database.add(job)
        database.commit()
        results = job_service.run_due_jobs(database, now=datetime.utcnow())
        database.refresh(job)
        notification = database.scalar(
            select(models.Notification).where(
                models.Notification.related_record_type == "scheduled_job",
                models.Notification.related_record_id == job.id,
            )
        )

    own_result = next(item for item in results if item["job_id"] == job.id)
    assert calls == [client_id]
    assert own_result["status"] == "failed"
    assert "client_provider_verification_failed:slack_workspace_mismatch" in own_result["error"]
    assert job.last_status == "failed"
    assert notification is not None
    assert "provider connection" in notification.requested_action.casefold() or "required connection" in notification.requested_action.casefold()
