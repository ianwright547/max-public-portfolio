"""Persisted daily priorities built from tasks, reports, and live client evidence."""

from datetime import date as calendar_date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.daily_planning_service import DailyPlanTaskError, convert_plan_item_to_task, generate_daily_plans
from app.database import get_database
from app.routes.tasks import require_client, task_response


router = APIRouter(tags=["daily plans"])


@router.post("/clients/{client_id}/daily-plan", response_model=schemas.DailyClientPlanRead)
def generate_client_daily_plan(
    client_id: str,
    request: schemas.DailyPlanGenerateRequest,
    database: Session = Depends(get_database),
) -> models.DailyClientPlan:
    """Generate or refresh today's plan; in-depth mode gathers live evidence."""
    client = require_client(database, client_id)
    if client.status == "archived":
        raise HTTPException(status_code=409, detail="Archived clients cannot receive new plans")
    plan = generate_daily_plans(
        database,
        client=client,
        depth=request.depth,
        focus=request.focus,
        created_by=request.created_by,
        create_tasks=request.create_tasks,
    )[0]
    database.commit()
    database.refresh(plan)
    return plan


@router.get("/clients/{client_id}/daily-plan", response_model=schemas.DailyClientPlanRead)
def read_client_daily_plan(
    client_id: str,
    plan_date: Optional[calendar_date] = None,
    database: Session = Depends(get_database),
) -> models.DailyClientPlan:
    require_client(database, client_id)
    requested_date = plan_date or calendar_date.today()
    plan = database.scalar(
        select(models.DailyClientPlan).where(
            models.DailyClientPlan.client_id == client_id,
            models.DailyClientPlan.plan_date == requested_date,
        )
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="No daily plan exists for this date")
    return plan


@router.post(
    "/clients/{client_id}/daily-plan/items/{item_index}/task",
    response_model=schemas.TaskRead,
    status_code=201,
)
def convert_daily_plan_item(
    client_id: str,
    item_index: int,
    request: schemas.DailyPlanTaskCreate,
    plan_date: Optional[calendar_date] = None,
    database: Session = Depends(get_database),
) -> dict:
    client = require_client(database, client_id)
    if client.status == "archived":
        raise HTTPException(status_code=409, detail="Archived clients cannot receive new tasks")
    requested_date = plan_date or calendar_date.today()
    plan = database.scalar(
        select(models.DailyClientPlan).where(
            models.DailyClientPlan.client_id == client_id,
            models.DailyClientPlan.plan_date == requested_date,
        )
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="No daily plan exists for this date")
    try:
        task, _reused = convert_plan_item_to_task(
            database,
            plan,
            item_index,
            created_by=request.created_by,
        )
    except DailyPlanTaskError as error:
        database.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    database.commit()
    database.refresh(task)
    return task_response(database, task)


@router.get("/daily-plans", response_model=list[schemas.DailyClientPlanRead])
def list_daily_plans(
    plan_date: Optional[calendar_date] = None,
    database: Session = Depends(get_database),
) -> list[models.DailyClientPlan]:
    requested_date = plan_date or calendar_date.today()
    return list(
        database.scalars(
            select(models.DailyClientPlan)
            .join(models.Client, models.Client.id == models.DailyClientPlan.client_id)
            .where(
                models.DailyClientPlan.plan_date == requested_date,
                models.Client.status != "archived",
            )
            .order_by(models.DailyClientPlan.client_id)
        )
    )
