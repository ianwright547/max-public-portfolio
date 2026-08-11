"""Small, provider-agnostic AI cost ledger and monthly safety gate."""

import os
import math
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models


class AIBudgetExceeded(RuntimeError):
    pass


def monthly_budget_usd() -> float:
    try:
        return max(0.0, float(os.getenv("MONTHLY_AI_BUDGET_USD", "50")))
    except ValueError:
        return 50.0


def month_range(now: datetime) -> tuple[datetime, datetime]:
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, next_month


def monthly_usage(database: Session, now: datetime, client_id: Optional[str] = None) -> float:
    start, end = month_range(now)
    statement = select(
        func.coalesce(
            func.sum(func.coalesce(models.AIUsageRecord.actual_cost_usd, models.AIUsageRecord.estimated_cost_usd)),
            0.0,
        )
    ).where(models.AIUsageRecord.created_at >= start, models.AIUsageRecord.created_at < end)
    if client_id is not None:
        statement = statement.where(models.AIUsageRecord.client_id == client_id)
    return float(database.scalar(statement) or 0.0)


def budget_status(used: float, budget: float) -> str:
    if budget <= 0 or used >= budget:
        return "stop"
    ratio = used / budget
    if ratio >= 0.8:
        return "strong_warning"
    if ratio >= 0.5:
        return "warning"
    return "within_budget"


def ensure_budget(database: Session, estimated_cost_usd: float, now: datetime) -> None:
    if not math.isfinite(estimated_cost_usd) or estimated_cost_usd < 0:
        raise ValueError("ai_cost_invalid")
    if monthly_usage(database, now) + estimated_cost_usd > monthly_budget_usd():
        raise AIBudgetExceeded("monthly_ai_budget_exceeded")


def record_usage(database: Session, **values) -> models.AIUsageRecord:
    estimated = values.get("estimated_cost_usd")
    actual = values.get("actual_cost_usd")
    if not isinstance(estimated, (int, float)) or not math.isfinite(float(estimated)) or estimated < 0:
        raise ValueError("ai_cost_invalid")
    if actual is not None and (not isinstance(actual, (int, float)) or not math.isfinite(float(actual)) or actual < 0):
        raise ValueError("ai_cost_invalid")
    existing = database.scalar(select(models.AIUsageRecord).where(models.AIUsageRecord.operation_key == values["operation_key"]))
    if existing is not None:
        return existing
    record = models.AIUsageRecord(**values)
    database.add(record)
    try:
        database.flush()
    except Exception as error:
        database.rollback()
        existing = database.scalar(select(models.AIUsageRecord).where(models.AIUsageRecord.operation_key == values["operation_key"]))
        if existing is not None:
            return existing
        raise error
    if record.client_id:
        status = budget_status(monthly_usage(database, record.created_at or datetime.utcnow()), monthly_budget_usd())
        if status in {"warning", "strong_warning", "stop"}:
            from app.notification_service import notify_ai_budget_threshold

            notify_ai_budget_threshold(database, record, status)
    return record
