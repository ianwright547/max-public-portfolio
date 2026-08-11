"""Read-only visibility into Max's persisted AI cost records."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.ai_cost_service import budget_status, monthly_budget_usd, monthly_usage
from app.database import get_database

router = APIRouter(tags=["ai costs"])


@router.get("/ai-costs/monthly", response_model=schemas.AIBudgetRead)
def read_monthly_budget(database: Session = Depends(get_database)) -> dict:
    now = datetime.utcnow()
    budget = monthly_budget_usd()
    used = monthly_usage(database, now)
    return {"month": now.strftime("%Y-%m"), "budget_usd": budget, "used_usd": used, "remaining_usd": max(0.0, budget - used), "status": budget_status(used, budget)}


@router.get("/clients/{client_id}/ai-costs", response_model=list[schemas.AIUsageRead])
def read_client_costs(client_id: str, database: Session = Depends(get_database)) -> list[models.AIUsageRecord]:
    if database.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return list(database.scalars(select(models.AIUsageRecord).where(models.AIUsageRecord.client_id == client_id).order_by(models.AIUsageRecord.created_at, models.AIUsageRecord.id)))


@router.get("/clients/{client_id}/ai-cost-summary", response_model=schemas.AIBudgetRead)
def read_client_cost_summary(client_id: str, database: Session = Depends(get_database)) -> dict:
    if database.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    now = datetime.utcnow()
    budget = monthly_budget_usd()
    used = monthly_usage(database, now, client_id=client_id)
    return {
        "month": now.strftime("%Y-%m"),
        "budget_usd": budget,
        "used_usd": used,
        "remaining_usd": max(0.0, budget - used),
        "status": budget_status(used, budget),
    }
