"""Slack connection endpoints and the agency-owner setup screen."""

from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
from html import escape
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import (
    ai_cost_service,
    models,
    schemas,
    slack_action_service,
    slack_conversation_service,
    slack_service,
)
from app.database import get_database
from app.audit import record_event
from app.agency_access_service import slack_member_for_user, slack_user_has_capability
from app.slack_service import (
    SlackClientMismatchError,
    SlackIntegrationError,
    connect_client_channel,
    deliver_saved_notification,
    rename_client_channel,
    recreate_client_public_channel,
    slack_owner_user_ids,
)


router = APIRouter(tags=["slack"])
TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "slack_setup.html"
logger = logging.getLogger(__name__)


def slack_action_failure_message(error: Exception, action_type: str) -> str:
    """Explain safe action failures in Slack without sending users to an admin screen."""
    if isinstance(error, SlackIntegrationError):
        explanations = {
            "slack_token_missing": "Slack is not fully connected yet. Add the bot token, then retry this command here.",
            "slack_channel_not_connected": "This client does not have a working Slack-channel mapping. Reconnect this channel, then retry here.",
            "slack_temporarily_unavailable": "Slack is temporarily unavailable. Nothing else was changed; retry this command here in a moment.",
        }
        return explanations.get(
            error.code,
            f"I couldn't finish `{action_type}` because Slack returned `{error.code}`. Fix that connection issue, then retry here.",
        )
    if isinstance(error, HTTPException):
        # FastAPI details are sometimes structured payloads (for example the
        # paid-mode entitlement gate). Never stringify those dictionaries into
        # Slack; users need a plain-language next step, not an internal API
        # representation.
        raw_detail = error.detail
        detail_code = ""
        detail_message = ""
        if isinstance(raw_detail, dict):
            detail_code = str(raw_detail.get("code") or "").replace("_", " ").strip().casefold()
            detail_message = str(raw_detail.get("message") or "").replace("_", " ").strip()
            detail = detail_code or detail_message
        else:
            detail = str(raw_detail).replace("_", " ").strip()
        known = {
            "archived client": "this client is already archived, so no new work was started",
            "client not found": "I could not find that client in Max",
            "task not found": "I could not find that task in Max",
            "report not found": "I could not find that report in Max",
            "report approval required": "the report must be approved before it can be delivered",
            "client slack channel is not connected": "this client channel is not connected to a usable Slack mapping",
            "browser control approval required": "the task needs its separate browser-control approval before submission",
            "billing subscription required": "an active subscription is required before fulfillment can start",
            "authentication required": "owner authentication is required before this action can run",
        }
        explanation = known.get(
            detail,
            detail_message or detail or "a validation or approval requirement was not met",
        )
        return f"I couldn't finish `{action_type}` because {explanation}. Nothing else was changed; correct that item and retry here."
    if isinstance(error, ValueError):
        detail = str(error).replace("_", " ").strip()
        return f"I couldn't finish `{action_type}` because {detail or 'required information is missing'}. Add the missing detail and retry here."
    return (
        f"I couldn't finish `{action_type}`. Nothing else was changed. "
        "Retry the request in this conversation; if it repeats, I’ll keep the failure details attached to this command."
    )


def slack_http_error(error: SlackIntegrationError) -> HTTPException:
    if isinstance(error, SlackClientMismatchError):
        return HTTPException(status_code=409, detail=error.code)
    configuration_errors = {"slack_token_missing", "slack_owner_user_id_missing"}
    status_code = 503 if error.retryable or error.code in configuration_errors else 502
    return HTTPException(status_code=status_code, detail=error.code)


def verify_slack_signature(body: bytes, timestamp: str, signature: str) -> None:
    signing_secret = os.getenv("SLACK_SIGNING_SECRET", "").strip()
    if not signing_secret:
        raise HTTPException(status_code=503, detail="slack_signing_secret_missing")
    try:
        request_time = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
    except (TypeError, ValueError, OSError) as error:
        raise HTTPException(status_code=401, detail="slack_signature_invalid") from error
    if abs((datetime.now(timezone.utc) - request_time).total_seconds()) > 300:
        raise HTTPException(status_code=401, detail="slack_request_expired")
    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    expected = "v0=" + hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="slack_signature_invalid")


@router.post("/slack/events", response_class=JSONResponse)
async def slack_events(request: Request, database: Session = Depends(get_database)) -> JSONResponse:
    """Acknowledge signed Slack events and answer mapped-channel mentions or owner DMs."""
    body = await request.body()
    verify_slack_signature(
        body,
        request.headers.get("X-Slack-Request-Timestamp", ""),
        request.headers.get("X-Slack-Signature", ""),
    )
    try:
        payload = json.loads(body)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="slack_event_payload_invalid") from error

    if payload.get("type") == "url_verification":
        challenge = payload.get("challenge")
        if not isinstance(challenge, str) or not challenge:
            raise HTTPException(status_code=400, detail="slack_challenge_missing")
        return JSONResponse({"challenge": challenge})
    if payload.get("type") != "event_callback":
        return JSONResponse({"ok": True, "status": "ignored"})

    workspace_id = str(payload.get("team_id") or "")
    expected_workspace_id = os.getenv("SLACK_WORKSPACE_ID", "").strip()
    if not expected_workspace_id:
        raise HTTPException(status_code=503, detail="slack_workspace_missing")
    if workspace_id != expected_workspace_id:
        raise HTTPException(status_code=403, detail="slack_workspace_mismatch")

    event = payload.get("event")
    if not isinstance(event, dict):
        return JSONResponse({"ok": True, "status": "ignored"})
    is_app_mention = event.get("type") == "app_mention"
    is_owner_dm = event.get("type") == "message" and event.get("channel_type") == "im"
    if not is_app_mention and not is_owner_dm:
        return JSONResponse({"ok": True, "status": "ignored"})
    # Never respond to bot-generated messages, even if Slack adds a mention subtype.
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return JSONResponse({"ok": True, "status": "ignored"})

    event_id = str(payload.get("event_id") or "")
    channel_id = str(event.get("channel") or "")
    user_id = str(event.get("user") or "")
    event_thread_ts = str(event.get("thread_ts") or "") or None
    thread_ts = event_thread_ts or (str(event.get("ts") or "") or None)
    if not event_id or not channel_id or not user_id:
        raise HTTPException(status_code=400, detail="slack_event_fields_missing")
    member = slack_member_for_user(database, user_id)
    legacy_owner = user_id in slack_owner_user_ids()
    member_can_read = legacy_owner or member is not None
    member_can_act = legacy_owner or slack_user_has_capability(database, user_id, "client_operations")

    action_key = f"event:{event_id}"
    receipt = database.scalar(
        select(models.SlackActionReceipt).where(models.SlackActionReceipt.action_key == action_key)
    )
    payload_hash = hashlib.sha256(body).hexdigest()
    if receipt is not None and receipt.result_status.startswith("responded"):
        if not hmac.compare_digest(receipt.payload_hash, payload_hash):
            raise HTTPException(status_code=409, detail="slack_event_payload_mismatch")
        return JSONResponse({"ok": True, "status": receipt.result_status, "duplicate": True})
    if receipt is not None and receipt.result_status == "pending":
        if not hmac.compare_digest(receipt.payload_hash, payload_hash):
            raise HTTPException(status_code=409, detail="slack_event_payload_mismatch")
        return JSONResponse({"ok": True, "status": "pending", "duplicate": True})

    slack = slack_service.get_slack_adapter()
    connection = None
    if is_app_mention:
        try:
            connection = slack_service.resolve_client_channel_connection(
                database, workspace_id, channel_id, slack, user_id
            )
        except SlackIntegrationError as error:
            logger.info(
                "slack_event status=resolution_failed code=%s workspace=%s channel=%s event=%s",
                error.code,
                workspace_id,
                channel_id,
                event_id,
            )
            raise HTTPException(status_code=503, detail=error.code) from error
    client = None
    response_status = "responded_unmapped"
    if connection is None or connection.connection_status not in {"connected", "connected_public"}:
        if is_owner_dm and not member_can_read:
            return JSONResponse({"ok": True, "status": "unauthorized_dm"})
        if is_app_mention and not member_can_read:
            logger.info(
                "slack_app_mention status=unmapped_channel workspace=%s channel=%s event=%s",
                workspace_id,
                channel_id,
                event_id,
            )
            return JSONResponse({"ok": True, "status": "unmapped_channel"})
    else:
        client = database.get(models.Client, connection.client_id)
        if client is None:
            raise HTTPException(status_code=409, detail="slack_client_missing")
        response_status = "responded"

    if receipt is None:
        receipt = models.SlackActionReceipt(
            action_key=action_key,
            payload_hash=payload_hash,
            slack_user_id=user_id,
            action_id="direct_message" if is_owner_dm else "app_mention",
            related_record_type="slack_channel",
            related_record_id=channel_id,
            result_status="pending",
        )
        database.add(receipt)
    else:
        receipt.result_status = "pending"
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        concurrent = database.scalar(
            select(models.SlackActionReceipt).where(models.SlackActionReceipt.action_key == action_key)
        )
        if concurrent is not None and hmac.compare_digest(concurrent.payload_hash, payload_hash):
            return JSONResponse({"ok": True, "status": concurrent.result_status, "duplicate": True})
        raise HTTPException(status_code=409, detail="slack_event_receipt_conflict")

    extracted_question = slack_conversation_service.extract_question(event.get("text"))
    question = slack_conversation_service.redact_sensitive_text(extracted_question)
    prior_turns = slack_conversation_service.conversation_history(
        database,
        workspace_id=workspace_id,
        channel_id=channel_id,
        thread_ts=event_thread_ts,
    )
    owner_action = None
    action_result = None
    action_interpretation = None
    intent_needs_clarification = False
    if question != extracted_question:
        logger.warning(
            "slack_app_mention status=credential_redacted workspace=%s channel=%s event=%s",
            workspace_id,
            channel_id,
            event_id,
        )
    if not question:
        answer_text = "Mention me with a question, for example: `@Max what should we prioritize this week?`"
        answer = None
    else:
        # A mapped client channel is itself an explicit authorization boundary:
        # anyone the agency has allowed into it may issue client-scoped commands.
        # DMs and unmapped channels remain restricted to configured agency owners.
        owner_action = (
            slack_action_service.detect_owner_action(
                question,
                has_mapped_client=client is not None,
            )
            if client is not None or member_can_act
            else None
        )
        if owner_action is None and slack_conversation_service.likely_action_request(question):
            try:
                ai_cost_service.ensure_budget(database, 0.002, datetime.now(timezone.utc))
                action_interpretation = slack_conversation_service.interpret_action(
                    question,
                    has_mapped_client=client is not None,
                )
                if action_interpretation is not None:
                    # Persist provider spend before executing the interpreted
                    # action. A later action failure may roll back its state;
                    # it must never erase the fact that the AI call happened.
                    ai_cost_service.record_usage(
                        database,
                        operation_key=f"slack-intent:{event_id}",
                        client_id=client.id if client is not None else None,
                        task_id=None,
                        provider="openai",
                        model=action_interpretation.model,
                        model_role="efficient",
                        operation="slack_action_intent_classification",
                        input_tokens=action_interpretation.input_tokens,
                        output_tokens=action_interpretation.output_tokens,
                        estimated_cost_usd=action_interpretation.estimated_cost_usd,
                        actual_cost_usd=None,
                    )
                    database.commit()
                if action_interpretation is not None and action_interpretation.canonical_command:
                    if action_interpretation.confidence < slack_conversation_service.ACTION_CONFIDENCE_THRESHOLD:
                        intent_needs_clarification = True
                    else:
                        owner_action = slack_action_service.detect_owner_action(
                            action_interpretation.canonical_command,
                            has_mapped_client=client is not None,
                        )
                    if owner_action is not None:
                        record_event(
                            database,
                            "slack_action_interpreted",
                            actor=f"slack:{user_id}",
                            client_id=client.id if client is not None else None,
                            record_type="slack_action",
                            record_id=event_id,
                            details={
                                "canonical_command": action_interpretation.canonical_command,
                                "confidence": action_interpretation.confidence,
                                "action_type": owner_action.action_type,
                            },
                        )
            except ai_cost_service.AIBudgetExceeded:
                action_interpretation = None
        if owner_action is not None:
            try:
                action_result = slack_action_service.apply_owner_action(
                    database,
                    owner_action,
                    slack_user_id=user_id,
                    event_id=event_id,
                    mapped_client=client,
                )
                database.commit()
                answer_text = action_result.text
                answer = None
            except Exception as error:
                logger.exception(
                    "slack_action status=failed workspace=%s channel=%s event=%s action=%s",
                    workspace_id,
                    channel_id,
                    event_id,
                    owner_action.action_type,
                )
                database.rollback()
                receipt = database.scalar(
                    select(models.SlackActionReceipt).where(
                        models.SlackActionReceipt.action_key == action_key
                    )
                )
                if receipt is None:
                    raise HTTPException(status_code=503, detail="slack_action_state_lost")
                response_status = "responded_failed"
                receipt.result_status = response_status
                record_event(
                    database,
                    "slack_action_failed",
                    actor=f"slack:{user_id}",
                    client_id=client.id if client is not None else None,
                    record_type="slack_action",
                    record_id=event_id,
                    details={"channel_id": channel_id, "action_type": owner_action.action_type},
                )
                database.commit()
                answer_text = slack_action_failure_message(error, owner_action.action_type)
                answer = None
        elif intent_needs_clarification:
            answer = None
            answer_text = (
                "I may have misunderstood the requested action, so I did not change anything. "
                "Please restate the command with the client, report, or task you mean."
            )
        else:
            try:
                ai_cost_service.ensure_budget(database, 0.01, datetime.now(timezone.utc))
                context = (
                    slack_conversation_service.verified_client_context(database, client)
                    if client is not None
                    else slack_conversation_service.verified_owner_context(database)
                )
                from app.slack_memory_service import relevant_memories

                memories = relevant_memories(
                    database,
                    workspace_id=workspace_id,
                    client_id=client.id if client is not None else None,
                    question=question,
                )
                if memories:
                    context = {**context, "durable_memory": memories}
                if prior_turns:
                    answer = slack_conversation_service.answer_question(
                        question,
                        client_context=context,
                        conversation_history=prior_turns,
                    )
                else:
                    answer = slack_conversation_service.answer_question(question, client_context=context)
                answer_text = answer.text
                ai_cost_service.record_usage(
                    database,
                    operation_key=f"slack:{event_id}",
                    client_id=client.id if client is not None else None,
                    task_id=None,
                    provider="openai",
                    model=answer.model,
                    model_role="efficient",
                    operation=(
                        "slack_client_question_answer"
                        if client is not None
                        else "slack_agency_question_answer"
                    ),
                    input_tokens=answer.input_tokens,
                    output_tokens=answer.output_tokens,
                    estimated_cost_usd=answer.estimated_cost_usd,
                    actual_cost_usd=None,
                )
                database.commit()
            except ai_cost_service.AIBudgetExceeded:
                answer = None
                answer_text = "I can’t answer with AI right now because Max’s monthly AI budget limit has been reached."
            except slack_conversation_service.SlackConversationError as error:
                logger.warning(
                    "slack_app_mention status=ai_failed code=%s workspace=%s channel=%s event=%s",
                    error.code,
                    workspace_id,
                    channel_id,
                    event_id,
                )
                answer = None
                answer_text = "I’m connected to Slack, but I couldn’t reach my AI service right now. Please try again."
            except Exception:
                logger.exception(
                    "slack_question status=failed workspace=%s channel=%s event=%s",
                    workspace_id,
                    channel_id,
                    event_id,
                )
                database.rollback()
                receipt = database.scalar(
                    select(models.SlackActionReceipt).where(
                        models.SlackActionReceipt.action_key == action_key
                    )
                )
                if receipt is None:
                    raise HTTPException(status_code=503, detail="slack_question_state_lost")
                response_status = "responded_failed"
                receipt.result_status = response_status
                record_event(
                    database,
                    "slack_question_failed",
                    actor=f"slack:{user_id}",
                    client_id=client.id if client is not None else None,
                    record_type="slack_conversation",
                    record_id=event_id,
                    details={"channel_id": channel_id},
                )
                database.commit()
                answer = None
                answer_text = "I couldn't answer that just now. Please retry in this conversation."

    heading = f"*Max · {client.business_name}*" if client is not None else "*Max*"
    reply = f"{heading}\n{answer_text}"
    try:
        result = slack.post_message(channel_id, reply, event_id)
        if result.channel_id != channel_id:
            raise SlackClientMismatchError("slack_response_channel_mismatch")
    except SlackIntegrationError as error:
        receipt.result_status = "failed"
        database.commit()
        raise HTTPException(status_code=503, detail=error.code) from error

    # Send the confirmation while the channel is still writable, then archive
    # it as the final step of a direct archive/delete command.
    if (
        owner_action is not None
        and action_result is not None
        and action_result.archive_channel_id is not None
    ):
        try:
            slack.archive_channel(action_result.archive_channel_id)
            if connection is not None:
                connection.connection_status = "archived"
                connection.last_verified_at = datetime.now(timezone.utc).replace(tzinfo=None)
                connection.last_error = None
            record_event(
                database,
                "slack_client_channel_archived",
                actor=f"slack:{user_id}",
                client_id=client.id if client is not None else None,
                record_type="slack_channel",
                record_id=action_result.archive_channel_id,
                details={"slack_event_id": event_id},
            )
        except SlackIntegrationError as error:
            if connection is not None:
                connection.last_error = error.code
            record_event(
                database,
                "slack_client_channel_archive_failed",
                actor=f"slack:{user_id}",
                client_id=client.id if client is not None else None,
                record_type="slack_channel",
                record_id=action_result.archive_channel_id,
                details={"slack_event_id": event_id, "error_code": error.code},
            )

    if action_interpretation is not None:
        ai_cost_service.record_usage(
            database,
            operation_key=f"slack-intent:{event_id}",
            client_id=client.id if client is not None else None,
            task_id=None,
            provider="openai",
            model=action_interpretation.model,
            model_role="efficient",
            operation="slack_action_intent_classification",
            input_tokens=action_interpretation.input_tokens,
            output_tokens=action_interpretation.output_tokens,
            estimated_cost_usd=action_interpretation.estimated_cost_usd,
            actual_cost_usd=None,
        )
    if answer is not None:
        ai_cost_service.record_usage(
            database,
            operation_key=f"slack:{event_id}",
            client_id=client.id if client is not None else None,
            task_id=None,
            provider="openai",
            model=answer.model,
            model_role="efficient",
            operation=(
                "slack_client_question_answer"
                if client is not None
                else "slack_agency_question_answer"
            ),
            input_tokens=answer.input_tokens,
            output_tokens=answer.output_tokens,
            estimated_cost_usd=answer.estimated_cost_usd,
            actual_cost_usd=None,
        )
        record_event(
            database,
            "slack_question_answered",
            actor=f"slack:{user_id}",
            client_id=client.id if client is not None else None,
            record_type="slack_conversation",
            record_id=event_id,
            details={
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "question": question,
                "answer": answer.text,
                "model": answer.model,
            },
        )
    database.add(
        models.SlackConversationTurn(
            event_id=event_id,
            workspace_id=workspace_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            slack_user_id=user_id,
            client_id=client.id if client is not None else None,
            question=question or "(empty mention)",
            answer=answer_text,
            action_type=owner_action.action_type if owner_action is not None else None,
            result_status=response_status,
        )
    )
    receipt.result_status = response_status
    database.commit()
    logger.info(
        "slack_app_mention status=%s workspace=%s channel=%s event=%s",
        response_status,
        workspace_id,
        channel_id,
        event_id,
    )
    return JSONResponse({"ok": True, "status": response_status, "duplicate": False})


@router.post("/slack/actions", response_class=JSONResponse)
async def slack_actions(request: Request, database: Session = Depends(get_database)) -> JSONResponse:
    """Apply one task decision from an owner or its mapped client channel."""
    body = await request.body()
    verify_slack_signature(
        body,
        request.headers.get("X-Slack-Request-Timestamp", ""),
        request.headers.get("X-Slack-Signature", ""),
    )
    from urllib.parse import parse_qs

    encoded = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    try:
        payload = json.loads(encoded["payload"][-1])
        action = payload["actions"][0]
        action_id = str(action["action_id"])
        task_id = str(action["value"])
        user_id = str(payload["user"]["id"])
        team_id = str(payload["team"]["id"])
        channel_id = str((payload.get("channel") or {}).get("id") or "")
        action_ts = str(action.get("action_ts") or payload.get("trigger_id") or "")
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="slack_action_payload_invalid") from error
    if team_id != os.getenv("SLACK_WORKSPACE_ID", "").strip():
        raise HTTPException(status_code=403, detail="slack_workspace_mismatch")
    if action_id not in {"max_task_approve", "max_task_reject"}:
        raise HTTPException(status_code=422, detail="slack_action_unsupported")
    action_key = f"{team_id}:{user_id}:{action_ts}:{action_id}:{task_id}"
    existing = database.scalar(
        select(models.SlackActionReceipt).where(models.SlackActionReceipt.action_key == action_key)
    )
    payload_hash = hashlib.sha256(body).hexdigest()
    if existing is not None:
        if not hmac.compare_digest(existing.payload_hash, payload_hash):
            raise HTTPException(status_code=409, detail="slack_action_payload_mismatch")
        return JSONResponse({"ok": True, "status": existing.result_status, "duplicate": True})
    from app.routes.tasks import decide_task, require_task

    decision_value = "approved" if action_id == "max_task_approve" else "rejected"
    task = require_task(database, task_id)
    mapped_connection = database.scalar(
        select(models.SlackChannelConnection).where(
            models.SlackChannelConnection.channel_id == channel_id,
            models.SlackChannelConnection.workspace_id == team_id,
            models.SlackChannelConnection.client_id == task.client_id,
            models.SlackChannelConnection.connection_status.in_({"connected", "connected_public"}),
        )
    )
    if user_id not in slack_owner_user_ids() and mapped_connection is None:
        raise HTTPException(status_code=403, detail="slack_channel_clearance_required")
    decision = schemas.TaskDecisionCreate(
        decision=decision_value,
        decision_maker=(
            f"Slack owner {user_id}"
            if user_id in slack_owner_user_ids()
            else f"Slack channel member {user_id}"
        ),
        reason=None if decision_value == "approved" else "Rejected from signed Slack approval button",
    )
    decide_task(database, task, decision)
    database.add(
        models.SlackActionReceipt(
            action_key=action_key,
            payload_hash=payload_hash,
            slack_user_id=user_id,
            action_id=action_id,
            related_record_type="task",
            related_record_id=task_id,
            result_status=decision_value,
        )
    )
    database.commit()
    return JSONResponse({"ok": True, "status": decision_value, "duplicate": False})


@router.post(
    "/clients/{client_id}/slack-channel",
    response_model=schemas.SlackChannelConnectionResult,
)
def create_client_slack_channel(
    client_id: str,
    database: Session = Depends(get_database),
) -> schemas.SlackChannelConnectionResult:
    try:
        connection, created = connect_client_channel(database, client_id)
    except ValueError as error:
        if str(error) == "client_not_found":
            raise HTTPException(status_code=404, detail="Client not found") from error
        raise
    except SlackIntegrationError as error:
        raise slack_http_error(error) from error
    database.commit()
    database.refresh(connection)
    return schemas.SlackChannelConnectionResult(connection=connection, created=created)


@router.get(
    "/clients/{client_id}/slack-channel",
    response_model=schemas.SlackChannelRead,
)
def read_client_slack_channel(
    client_id: str,
    database: Session = Depends(get_database),
) -> models.SlackChannelConnection:
    if database.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    connection = database.scalar(
        select(models.SlackChannelConnection).where(
            models.SlackChannelConnection.client_id == client_id
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Slack channel not connected")
    return connection


@router.post(
    "/clients/{client_id}/slack-channel/rename",
    response_model=schemas.SlackChannelRead,
)
def rename_client_slack_channel(
    client_id: str,
    database: Session = Depends(get_database),
) -> models.SlackChannelConnection:
    """Apply the clean business-name display while retaining backend IDs."""
    try:
        return rename_client_channel(database, client_id)
    except ValueError as error:
        if str(error) == "client_not_found":
            raise HTTPException(status_code=404, detail="Client not found") from error
        raise
    except SlackIntegrationError as error:
        raise slack_http_error(error) from error


@router.post(
    "/clients/{client_id}/slack-channel/recreate-public",
    response_model=schemas.SlackChannelRead,
)
def recreate_public_slack_channel(
    client_id: str,
    database: Session = Depends(get_database),
) -> models.SlackChannelConnection:
    try:
        connection = recreate_client_public_channel(database, client_id)
    except ValueError as error:
        if str(error) == "client_not_found":
            raise HTTPException(status_code=404, detail="Client not found") from error
        raise
    except SlackIntegrationError as error:
        raise slack_http_error(error) from error
    database.commit()
    database.refresh(connection)
    return connection


@router.post(
    "/clients/{client_id}/slack-channel/archive",
    response_model=schemas.SlackChannelRead,
)
def archive_client_slack_channel(
    client_id: str,
    database: Session = Depends(get_database),
) -> models.SlackChannelConnection:
    """Retry cleanup after a client removal when Slack was temporarily unavailable."""
    if database.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    connection = database.scalar(
        select(models.SlackChannelConnection).where(
            models.SlackChannelConnection.client_id == client_id
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Slack channel not connected")
    if connection.connection_status != "archived":
        try:
            slack_service.get_slack_adapter().archive_channel(connection.channel_id)
        except SlackIntegrationError as error:
            connection.connection_status = "archive_pending"
            connection.last_error = error.code
            database.commit()
            raise slack_http_error(error) from error
        connection.connection_status = "archived"
        connection.last_error = None
    database.commit()
    database.refresh(connection)
    return connection


@router.post(
    "/notifications/{notification_id}/slack-delivery",
    response_model=schemas.SlackDeliveryRead,
)
def retry_slack_delivery(
    notification_id: str,
    database: Session = Depends(get_database),
) -> models.SlackDelivery:
    notification = database.get(models.Notification, notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    try:
        delivery = deliver_saved_notification(database, notification)
    except SlackIntegrationError as error:
        raise slack_http_error(error) from error
    if delivery is None:
        raise HTTPException(status_code=409, detail="Client Slack channel is not connected")
    database.commit()
    database.refresh(delivery)
    return delivery


def render_client_row(
    client: models.Client,
    connection: Optional[models.SlackChannelConnection],
) -> str:
    if connection is None:
        state = '<span class="slack-state disconnected">Not connected</span>'
        action = (
            f'<form method="post" action="/dashboard/slack/clients/{escape(client.id)}/connect">'
            '<button type="submit">Create public channel</button></form>'
        )
        channel = "—"
    else:
        state = f'<span class="slack-state connected">{escape(connection.connection_status)}</span>'
        action = '<span class="slack-verified">Mapping saved</span>'
        channel = f"#{escape(connection.channel_name)}"
    return f"""
      <tr>
        <td><strong>{escape(client.business_name)}</strong><small>{escape(client.id)}</small></td>
        <td>{channel}</td>
        <td>{state}</td>
        <td>{action}</td>
      </tr>
    """


@router.get("/dashboard/slack", response_class=HTMLResponse)
def slack_dashboard(database: Session = Depends(get_database)) -> HTMLResponse:
    clients = list(database.scalars(select(models.Client).order_by(models.Client.business_name)))
    connections = {
        item.client_id: item
        for item in database.scalars(select(models.SlackChannelConnection))
    }
    rows = "".join(render_client_row(client, connections.get(client.id)) for client in clients)
    if not rows:
        rows = '<tr><td colspan="4">Create a client before connecting a Slack channel.</td></tr>'
    configured = bool(os.getenv("SLACK_BOT_TOKEN", "").strip())
    workspace_id = os.getenv("SLACK_WORKSPACE_ID", "").strip()
    owner_ids = os.getenv("SLACK_OWNER_USER_IDS", "").strip()
    if configured and workspace_id and owner_ids:
        status = "Configured"
    elif configured and workspace_id:
        status = "Waiting for owner member ID"
    else:
        status = "Waiting for Slack credentials"
    page = TEMPLATE_PATH.read_text(encoding="utf-8")
    page = page.replace("{{SLACK_STATUS}}", escape(status))
    page = page.replace("{{CONNECTED_COUNT}}", str(len(connections)))
    page = page.replace("{{CLIENT_COUNT}}", str(len(clients)))
    page = page.replace("{{CLIENT_ROWS}}", rows)
    return HTMLResponse(page)


@router.post("/dashboard/slack/clients/{client_id}/connect", response_class=RedirectResponse)
def dashboard_connect_client_channel(
    client_id: str,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    create_client_slack_channel(client_id, database)
    return RedirectResponse(url="/dashboard/slack", status_code=303)
