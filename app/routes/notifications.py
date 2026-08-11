"""Phase 12 internal notification inbox; no external delivery is connected."""

from datetime import datetime
from html import escape
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_database
from app.routes.tasks import require_client


router = APIRouter(tags=["notifications"])
TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "notifications.html"


def notification_query(client_id: Optional[str] = None, unread_only: bool = False):
    statement = select(models.Notification)
    if client_id:
        statement = statement.where(models.Notification.client_id == client_id)
    if unread_only:
        statement = statement.where(models.Notification.is_read.is_(False))
    return statement.order_by(
        models.Notification.is_read,
        models.Notification.created_at.desc(),
        models.Notification.id.desc(),
    )


@router.get("/notifications", response_model=list[schemas.NotificationRead])
def list_notifications(
    client_id: Optional[str] = None,
    unread_only: bool = False,
    database: Session = Depends(get_database),
) -> list[models.Notification]:
    if client_id:
        require_client(database, client_id)
    return list(database.scalars(notification_query(client_id, unread_only)))


@router.post("/notifications/{notification_id}/read", response_model=schemas.NotificationRead)
def mark_notification_read(
    notification_id: str,
    database: Session = Depends(get_database),
) -> models.Notification:
    notification = database.get(models.Notification, notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.utcnow()
        database.commit()
        database.refresh(notification)
    return notification


def related_link(notification: models.Notification) -> str:
    record_type = notification.related_record_type
    record_id = notification.related_record_id
    if record_type == "report":
        return f"/reports/{escape(record_id)}/html"
    if record_type == "task":
        return f"/tasks/{escape(record_id)}"
    if record_type == "execution":
        return f"/executions/{escape(record_id)}"
    return f"/dashboard/clients/{escape(notification.client_id)}/health"


def render_notification(database: Session, notification: models.Notification) -> str:
    client = database.get(models.Client, notification.client_id)
    read_class = "is-read" if notification.is_read else "is-unread"
    read_control = (
        '<span class="notification-read-label">Read</span>'
        if notification.is_read
        else f'<form method="post" action="/dashboard/notifications/{escape(notification.id)}/read"><button type="submit">Mark read</button></form>'
    )
    return f"""
      <article class="notification-row {read_class} importance-{escape(notification.importance)}">
        <div class="notification-main"><span>{escape(client.business_name)} · {escape(notification.category.replace('_', ' '))}</span><h2>{escape(notification.explanation)}</h2><p><strong>Requested action</strong>{escape(notification.requested_action)}</p></div>
        <div class="notification-meta"><span class="importance">{escape(notification.importance)}</span><time>{notification.created_at.strftime('%b %d, %Y %I:%M %p')}</time><a href="{related_link(notification)}">{escape(notification.related_record_type)} · {escape(notification.related_record_id)}</a>{read_control}</div>
      </article>
    """


@router.get("/dashboard/notifications", response_class=HTMLResponse)
def notification_dashboard(
    client_id: Optional[str] = None,
    unread_only: bool = False,
    database: Session = Depends(get_database),
) -> HTMLResponse:
    if client_id:
        require_client(database, client_id)
    notifications = list(database.scalars(notification_query(client_id, unread_only)))
    clients = list(database.scalars(select(models.Client).order_by(models.Client.business_name)))
    options = ['<option value="">All clients</option>']
    for client in clients:
        selected = " selected" if client.id == client_id else ""
        options.append(
            f'<option value="{escape(client.id)}"{selected}>{escape(client.business_name)}</option>'
        )
    rows = "".join(render_notification(database, item) for item in notifications)
    if not rows:
        rows = '<p class="notification-empty">No meaningful notifications match this view.</p>'
    unread_count = database.scalar(
        select(models.Notification.id).where(models.Notification.is_read.is_(False)).limit(1)
    )
    total_unread = len(
        list(database.scalars(select(models.Notification.id).where(models.Notification.is_read.is_(False))))
    ) if unread_count else 0
    page = TEMPLATE_PATH.read_text(encoding="utf-8")
    page = page.replace("{{UNREAD_COUNT}}", str(total_unread))
    page = page.replace("{{CLIENT_OPTIONS}}", "".join(options))
    page = page.replace("{{UNREAD_CHECKED}}", " checked" if unread_only else "")
    page = page.replace("{{NOTIFICATIONS}}", rows)
    slack_configured = bool(
        os.getenv("SLACK_BOT_TOKEN", "").strip()
        and os.getenv("SLACK_WORKSPACE_ID", "").strip()
        and os.getenv("SLACK_OWNER_USER_IDS", "").strip()
    )
    page = page.replace(
        "{{SLACK_STATUS}}",
        "Slack configured" if slack_configured else "Slack disconnected",
    )
    page = page.replace(
        "{{SLACK_BOUNDARY_TITLE}}",
        "Internal + Slack delivery" if slack_configured else "No Slack connection",
    )
    page = page.replace(
        "{{SLACK_BOUNDARY_TEXT}}",
        (
            "Every event remains saved here. Client-matched events are also sent to their verified private Slack channel."
            if slack_configured
            else "Events are delivered only to this internal inbox. Healthy checks, routine success, background work, duplicates, and small changes remain quiet."
        ),
    )
    return HTMLResponse(page)


@router.post("/dashboard/notifications/{notification_id}/read", response_class=RedirectResponse)
def notification_dashboard_read(
    notification_id: str,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    mark_notification_read(notification_id, database)
    return RedirectResponse(url="/dashboard/notifications", status_code=303)
