"""Compact, explicit Slack memory with strict agency/client scoping."""

from __future__ import annotations

from datetime import datetime
import hashlib
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models


MAX_MEMORY_CONTENT = 1200
MAX_RETRIEVED_MEMORIES = 6
MAX_RETRIEVED_CHARACTERS = 2400
ALWAYS_RELEVANT_CATEGORIES = {"style", "preference"}


def _scope_query(workspace_id: str, client_id: str | None):
    query = select(models.SlackMemory).where(
        models.SlackMemory.workspace_id == workspace_id,
        models.SlackMemory.is_active.is_(True),
    )
    if client_id is None:
        return query.where(models.SlackMemory.client_id.is_(None))
    return query.where(models.SlackMemory.client_id == client_id)


def _terms(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) >= 3
    }


def save_memory(
    database: Session,
    *,
    workspace_id: str,
    client_id: str | None,
    slack_user_id: str,
    content: str,
    category: str = "general",
) -> tuple[models.SlackMemory, bool]:
    value = " ".join(content.split()).strip()
    if not value:
        raise ValueError("memory_content_required")
    if "[REDACTED CREDENTIAL]" in value:
        raise ValueError("memory_contains_credential")
    value = value[:MAX_MEMORY_CONTENT]
    key = (
        "response_style"
        if category == "style"
        else hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()[:24]
    )
    existing = database.scalar(
        _scope_query(workspace_id, client_id).where(models.SlackMemory.memory_key == key)
    )
    if existing is not None:
        existing.content = value
        existing.category = category
        existing.updated_by = slack_user_id
        existing.updated_at = datetime.utcnow()
        database.flush()
        return existing, False
    memory = models.SlackMemory(
        workspace_id=workspace_id,
        client_id=client_id,
        memory_key=key,
        category=category,
        content=value,
        created_by=slack_user_id,
        updated_by=slack_user_id,
    )
    database.add(memory)
    database.flush()
    return memory, True


def update_memory(
    database: Session,
    *,
    memory_id: str,
    workspace_id: str,
    client_id: str | None,
    slack_user_id: str,
    content: str,
) -> models.SlackMemory:
    memory = database.scalar(
        _scope_query(workspace_id, client_id).where(models.SlackMemory.id == memory_id)
    )
    if memory is None:
        raise ValueError("memory_not_found_in_scope")
    value = " ".join(content.split()).strip()
    if not value:
        raise ValueError("memory_content_required")
    if "[REDACTED CREDENTIAL]" in value:
        raise ValueError("memory_contains_credential")
    memory.content = value[:MAX_MEMORY_CONTENT]
    memory.updated_by = slack_user_id
    memory.updated_at = datetime.utcnow()
    database.flush()
    return memory


def forget_memory(
    database: Session,
    *,
    memory_id: str,
    workspace_id: str,
    client_id: str | None,
    slack_user_id: str,
) -> models.SlackMemory:
    memory = database.scalar(
        _scope_query(workspace_id, client_id).where(models.SlackMemory.id == memory_id)
    )
    if memory is None:
        raise ValueError("memory_not_found_in_scope")
    memory.is_active = False
    memory.updated_by = slack_user_id
    memory.updated_at = datetime.utcnow()
    database.flush()
    return memory


def list_memories(
    database: Session, *, workspace_id: str, client_id: str | None, limit: int = 20
) -> list[models.SlackMemory]:
    return list(
        database.scalars(
            _scope_query(workspace_id, client_id)
            .order_by(models.SlackMemory.updated_at.desc(), models.SlackMemory.id.desc())
            .limit(max(1, min(limit, 50)))
        )
    )


def relevant_memories(
    database: Session,
    *,
    workspace_id: str,
    client_id: str | None,
    question: str,
) -> list[dict[str, str]]:
    question_terms = _terms(question)
    candidates = list_memories(
        database, workspace_id=workspace_id, client_id=client_id, limit=50
    )
    scored = []
    for memory in candidates:
        overlap = len(question_terms & _terms(memory.content))
        if memory.category in ALWAYS_RELEVANT_CATEGORIES or overlap:
            priority = 100 if memory.category == "style" else 50 if memory.category == "preference" else overlap
            scored.append((priority, memory.updated_at, memory))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    results: list[dict[str, str]] = []
    used = 0
    for _, _, memory in scored:
        size = len(memory.content)
        if results and used + size > MAX_RETRIEVED_CHARACTERS:
            continue
        results.append(
            {"id": memory.id, "category": memory.category, "content": memory.content}
        )
        used += size
        if len(results) >= MAX_RETRIEVED_MEMORIES:
            break
    return results


def previous_user_message(
    database: Session,
    *,
    workspace_id: str,
    client_id: str | None,
    current_event_id: str,
) -> str | None:
    query = select(models.SlackConversationTurn).where(
        models.SlackConversationTurn.workspace_id == workspace_id,
        models.SlackConversationTurn.event_id != current_event_id,
    )
    if client_id is None:
        query = query.where(models.SlackConversationTurn.client_id.is_(None))
    else:
        query = query.where(models.SlackConversationTurn.client_id == client_id)
    turn = database.scalar(
        query.order_by(models.SlackConversationTurn.created_at.desc(), models.SlackConversationTurn.id.desc())
    )
    return turn.question if turn is not None else None
