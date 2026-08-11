"""AI cost records are client-scoped, idempotent, and budget-gated."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.ai_cost_service import AIBudgetExceeded, ensure_budget, record_usage
from app.database import SessionLocal
from app.main import app


def make_client(client: TestClient, name: str) -> str:
    response = client.post("/clients", json={"business_name": name, "service_start_date": "2026-08-10"})
    assert response.status_code == 201
    return response.json()["id"]


def test_usage_is_idempotent_and_client_scoped() -> None:
    with TestClient(app) as client:
        first_id = make_client(client, "AI Cost First")
        second_id = make_client(client, "AI Cost Second")
        with SessionLocal() as database:
            first = record_usage(database, operation_key="ai-cost-first", client_id=first_id, task_id=None, provider="openai", model="test", model_role="balanced", operation="test", input_tokens=10, output_tokens=5, estimated_cost_usd=2.5, actual_cost_usd=None)
            same = record_usage(database, operation_key="ai-cost-first", client_id=first_id, task_id=None, provider="openai", model="test", model_role="balanced", operation="test", input_tokens=10, output_tokens=5, estimated_cost_usd=2.5, actual_cost_usd=None)
            database.commit()
            assert first.id == same.id
        first_costs = client.get(f"/clients/{first_id}/ai-costs")
        second_costs = client.get(f"/clients/{second_id}/ai-costs")
        monthly = client.get("/ai-costs/monthly")

    assert len(first_costs.json()) == 1
    assert second_costs.json() == []
    assert monthly.json()["used_usd"] >= 2.5


def test_budget_gate_stops_nonessential_ai_over_monthly_limit(monkeypatch) -> None:
    monkeypatch.setenv("MONTHLY_AI_BUDGET_USD", "1.00")
    with TestClient(app) as client:
        client_id = make_client(client, "AI Budget Client")
        with SessionLocal() as database:
            record_usage(database, operation_key="ai-budget-used", client_id=client_id, task_id=None, provider="openai", model="test", model_role="balanced", operation="test", input_tokens=None, output_tokens=None, estimated_cost_usd=1.0, actual_cost_usd=None)
            database.commit()
            with pytest.raises(AIBudgetExceeded, match="monthly_ai_budget_exceeded"):
                ensure_budget(database, 0.01, datetime.utcnow())


def test_budget_status_uses_percent_of_configured_budget_and_actual_cost(monkeypatch) -> None:
    monkeypatch.setenv("MONTHLY_AI_BUDGET_USD", "10.00")
    with TestClient(app) as client:
        client_id = make_client(client, "AI Actual Cost Client")
        with SessionLocal() as database:
            record_usage(
                database,
                operation_key="ai-actual-cost",
                client_id=client_id,
                task_id=None,
                provider="openai",
                model="test",
                model_role="balanced",
                operation="test",
                input_tokens=None,
                output_tokens=None,
                estimated_cost_usd=1.0,
                actual_cost_usd=8.5,
            )
            database.commit()
        monthly = client.get("/ai-costs/monthly")
        summary = client.get(f"/clients/{client_id}/ai-cost-summary")
        notifications = client.get(f"/notifications?client_id={client_id}")

    assert monthly.json()["used_usd"] >= 8.5
    assert summary.json()["used_usd"] >= 8.5
    assert summary.json()["status"] == "strong_warning"
    assert any(item["category"] == "cost_threshold_exceeded" for item in notifications.json())


def test_invalid_ai_cost_is_rejected() -> None:
    with TestClient(app) as client:
        client_id = make_client(client, "AI Invalid Cost Client")
        with SessionLocal() as database:
            with pytest.raises(ValueError, match="ai_cost_invalid"):
                record_usage(
                    database,
                    operation_key="ai-invalid-cost",
                    client_id=client_id,
                    task_id=None,
                    provider="openai",
                    model="test",
                    model_role="balanced",
                    operation="test",
                    input_tokens=None,
                    output_tokens=None,
                    estimated_cost_usd=-1.0,
                    actual_cost_usd=None,
                )
