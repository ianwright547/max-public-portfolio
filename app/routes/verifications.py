"""Phase 10 human verification and finding resolution."""

import json
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, quote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_database
from app.notification_service import notify_verification_failure
from app.routes.tasks import add_status_event, require_task
from app.verification_rules import confirmation_values, evaluate_execution, validate_requested_outcome


router = APIRouter(tags=["execution verification"])
TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "verification_review.html"


def require_execution(database: Session, execution_id: str) -> models.FulfillmentExecution:
    execution = database.get(models.FulfillmentExecution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


def verification_response(
    decision: models.ExecutionVerification,
    reused_existing: bool = False,
) -> dict:
    return {
        "id": decision.id,
        "decision_key": decision.decision_key,
        "client_id": decision.client_id,
        "task_id": decision.task_id,
        "execution_id": decision.execution_id,
        "outcome": decision.outcome,
        "reviewer": decision.reviewer,
        "explanation": decision.explanation,
        "review_evidence": decision.review_evidence,
        "confirmations": decision.confirmations,
        "validation_results": decision.validation_results,
        "decided_at": decision.decided_at,
        "resolved_finding": decision.outcome == "verified",
        "reused_existing": reused_existing,
    }


def review_execution(
    database: Session,
    execution_id: str,
    review: schemas.ExecutionVerificationCreate,
) -> tuple[models.ExecutionVerification, bool]:
    """Save one idempotent review and apply its allowed state effect."""
    existing = database.scalar(
        select(models.ExecutionVerification).where(
            models.ExecutionVerification.decision_key == review.decision_key
        )
    )
    if existing is not None:
        if existing.execution_id != execution_id:
            raise HTTPException(status_code=409, detail="Decision key belongs to another execution")
        return existing, True

    if any(not item.strip() for item in review.review_evidence):
        raise HTTPException(status_code=422, detail="Review evidence cannot contain blank entries")

    execution = require_execution(database, execution_id)
    task = require_task(database, execution.task_id)
    finding = database.get(models.Finding, task.source_finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Source finding not found")
    if execution.client_id != task.client_id or finding.client_id != task.client_id:
        raise HTTPException(status_code=409, detail="Execution, task, and finding must belong to one client")
    if execution.status != "completed" or task.status != "completed":
        raise HTTPException(
            status_code=409,
            detail="Only a completed execution for a completed task can be reviewed",
        )

    approval_exists = database.scalar(
        select(models.TaskDecision.id).where(
            models.TaskDecision.task_id == task.id,
            models.TaskDecision.client_id == task.client_id,
            models.TaskDecision.decision == "approved",
        )
    ) is not None
    content_review_approved = True
    packet_id = str((execution.evidence or {}).get("packet_id") or "")
    if packet_id:
        packet = database.get(models.CodexWorkPacket, packet_id)
        if packet is not None and (packet.packet_data or {}).get("local_seo_work_type") in {"local_page", "blog"}:
            content_review_approved = database.scalar(
                select(models.ContentReview.id).where(
                    models.ContentReview.packet_id == packet.id,
                    models.ContentReview.execution_id == execution.id,
                    models.ContentReview.status == "approved",
                )
            ) is not None
    results = evaluate_execution(task, execution, review, approval_exists, content_review_approved)
    validate_requested_outcome(review.outcome, results)

    decision = models.ExecutionVerification(
        decision_key=review.decision_key,
        client_id=task.client_id,
        task_id=task.id,
        execution_id=execution.id,
        outcome=review.outcome,
        reviewer=review.reviewer,
        explanation=review.explanation,
        review_evidence=review.review_evidence,
        confirmations=confirmation_values(review),
        validation_results=results,
        decided_at=datetime.utcnow(),
    )
    database.add(decision)
    database.flush()
    notify_verification_failure(database, decision)

    if review.outcome == "verified":
        task.status = "verified"
        finding.status = "resolved"
        finding.resolved_at = decision.decided_at
        add_status_event(
            database,
            task,
            "completed",
            "verified",
            review.reviewer,
            review.explanation,
        )
    elif review.outcome == "verification_failed":
        task.status = "failed"
        add_status_event(
            database,
            task,
            "completed",
            "failed",
            review.reviewer,
            f"Verification failed: {review.explanation}",
        )

    database.commit()
    database.refresh(decision)
    return decision, False


@router.post(
    "/executions/{execution_id}/verifications",
    response_model=schemas.ExecutionVerificationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_verification(
    execution_id: str,
    review: schemas.ExecutionVerificationCreate,
    database: Session = Depends(get_database),
) -> dict:
    decision, reused = review_execution(database, execution_id, review)
    return verification_response(decision, reused)


@router.get(
    "/executions/{execution_id}/verifications",
    response_model=list[schemas.ExecutionVerificationRead],
)
def list_execution_verifications(
    execution_id: str,
    database: Session = Depends(get_database),
) -> list[dict]:
    require_execution(database, execution_id)
    decisions = list(
        database.scalars(
            select(models.ExecutionVerification)
            .where(models.ExecutionVerification.execution_id == execution_id)
            .order_by(models.ExecutionVerification.decided_at, models.ExecutionVerification.id)
        )
    )
    return [verification_response(decision) for decision in decisions]


def list_items(values: list) -> str:
    if not values:
        return '<li class="empty-value">None recorded</li>'
    return "".join(f"<li>{escape(str(value))}</li>" for value in values)


def render_pending_review(
    database: Session,
    execution: models.FulfillmentExecution,
) -> str:
    task = database.get(models.Task, execution.task_id)
    client = database.get(models.Client, execution.client_id)
    approved = database.scalar(
        select(models.TaskDecision).where(
            models.TaskDecision.task_id == task.id,
            models.TaskDecision.decision == "approved",
        )
    )
    approved_by = approved.decision_maker if approved else "No approval record"
    decision_key = f"review-{execution.id}-{uuid4().hex[:10]}"
    tests = "".join(
        f'<li><strong>{escape(str(item.get("name", "test")))}</strong> {escape(str(item.get("status", "unknown")))}</li>'
        for item in execution.simulated_test_results
    ) or '<li class="empty-value">No tests recorded</li>'
    return f"""
      <article class="verification-card">
        <header><div><span>{escape(client.business_name)} · completed execution</span><h2>{escape(task.title)}</h2></div><code>{escape(execution.id)}</code></header>
        <section class="approved-request"><h3>Approved request</h3><p>{escape(task.requested_outcome)}</p><small>Approved by {escape(approved_by)}</small><dl><div><dt>Expected result</dt><dd>{escape(task.expected_result)}</dd></div><div><dt>Success metric</dt><dd>{escape(task.success_metric)}</dd></div><div><dt>Verification window</dt><dd>{escape(task.verification_window)}</dd></div></dl></section>
        <div class="verification-columns">
          <section><h3>Execution actions</h3><ul>{list_items(execution.intended_actions)}</ul></section>
          <section><h3>Changed files</h3><ul>{list_items(execution.simulated_changed_files)}</ul></section>
          <section><h3>Test results</h3><ul>{tests}</ul></section>
        </div>
        <section class="execution-evidence"><h3>Execution evidence</h3><pre>{escape(json.dumps(execution.evidence, indent=2, sort_keys=True))}</pre></section>
        <form method="post" action="/dashboard/executions/{escape(execution.id)}/verify">
          <div class="verification-fields">
            <label>Reviewer<input name="reviewer" required placeholder="Your name"></label>
            <label>Decision<select name="outcome"><option value="verified">Verified</option><option value="verification_failed">Verification failed</option><option value="needs_manual_review">Needs manual review</option><option value="not_enough_evidence">Not enough evidence</option></select></label>
          </div>
          <label>Explanation<textarea name="explanation" required placeholder="Explain why this decision is correct"></textarea></label>
          <label>Review evidence<textarea name="review_evidence" required placeholder="One supporting fact per line"></textarea></label>
          <fieldset><legend>Confirm each item after comparing the request and result</legend>
            <label><input type="checkbox" name="correct_client_confirmed" value="true"> Correct client</label>
            <label><input type="checkbox" name="approved_task_followed" value="true"> Approved task followed</label>
            <label><input type="checkbox" name="output_exists" value="true"> Output exists</label>
            <label><input type="checkbox" name="result_matches_requested_outcome" value="true"> Requested outcome matches</label>
            <label><input type="checkbox" name="no_unexpected_changes" value="true"> No unexpected changes</label>
          </fieldset>
          <input type="hidden" name="decision_key" value="{escape(decision_key)}">
          <button type="submit">Record verification decision</button>
        </form>
      </article>
    """


def render_review_history(database: Session, decision: models.ExecutionVerification) -> str:
    task = database.get(models.Task, decision.task_id)
    client = database.get(models.Client, decision.client_id)
    failed_checks = [name.replace("_", " ") for name, passed in decision.validation_results.items() if not passed]
    failed_text = ", ".join(failed_checks) or "All checks passed"
    return f"""
      <article class="verification-history status-{escape(decision.outcome)}">
        <div><span>{escape(client.business_name)} · {escape(decision.outcome.replace('_', ' '))}</span><h3>{escape(task.title)}</h3><p>{escape(decision.explanation)}</p></div>
        <dl><div><dt>Reviewer</dt><dd>{escape(decision.reviewer)}</dd></div><div><dt>Review evidence</dt><dd>{escape(' · '.join(decision.review_evidence))}</dd></div><div><dt>Failed checks</dt><dd>{escape(failed_text)}</dd></div></dl>
      </article>
    """


@router.get("/dashboard/verifications", response_class=HTMLResponse)
def verification_dashboard(
    database: Session = Depends(get_database),
    message: str = "",
    error: str = "",
) -> HTMLResponse:
    completed_executions = list(
        database.scalars(
            select(models.FulfillmentExecution)
            .where(models.FulfillmentExecution.status == "completed")
            .order_by(models.FulfillmentExecution.completed_at, models.FulfillmentExecution.id)
        )
    )
    pending = [
        execution
        for execution in completed_executions
        if database.get(models.Task, execution.task_id).status == "completed"
    ]
    decisions = list(
        database.scalars(
            select(models.ExecutionVerification)
            .order_by(models.ExecutionVerification.decided_at.desc())
            .limit(30)
        )
    )
    pending_rows = "".join(render_pending_review(database, execution) for execution in pending)
    if not pending_rows:
        pending_rows = '<p class="approval-empty">No completed executions are waiting for review.</p>'
    history_rows = "".join(render_review_history(database, decision) for decision in decisions)
    if not history_rows:
        history_rows = '<p class="approval-empty">No verification decisions have been recorded.</p>'
    notice = f'<p class="form-notice success-notice">{escape(message)}</p>' if message else ""
    if error:
        notice = f'<p class="form-notice error-notice">{escape(error)}</p>'
    page = TEMPLATE_PATH.read_text(encoding="utf-8")
    page = page.replace("{{PENDING_COUNT}}", str(len(pending)))
    page = page.replace("{{PENDING_REVIEWS}}", pending_rows)
    page = page.replace("{{REVIEW_HISTORY}}", history_rows).replace("{{NOTICE}}", notice)
    return HTMLResponse(page)


@router.post("/dashboard/executions/{execution_id}/verify", response_class=RedirectResponse)
async def verification_dashboard_submit(
    execution_id: str,
    request: Request,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    encoded = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    values = {key: entries[-1] for key, entries in encoded.items()}
    try:
        review = schemas.ExecutionVerificationCreate(
            decision_key=values.get("decision_key", ""),
            outcome=values.get("outcome", ""),
            reviewer=values.get("reviewer", ""),
            explanation=values.get("explanation", ""),
            review_evidence=[
                line.strip()
                for line in values.get("review_evidence", "").splitlines()
                if line.strip()
            ],
            correct_client_confirmed=values.get("correct_client_confirmed") == "true",
            approved_task_followed=values.get("approved_task_followed") == "true",
            output_exists=values.get("output_exists") == "true",
            result_matches_requested_outcome=values.get("result_matches_requested_outcome") == "true",
            no_unexpected_changes=values.get("no_unexpected_changes") == "true",
        )
        decision, reused = review_execution(database, execution_id, review)
    except (HTTPException, ValidationError) as exc:
        database.rollback()
        detail = getattr(exc, "detail", str(exc))
        return RedirectResponse(url=f"/dashboard/verifications?error={quote(str(detail))}", status_code=303)
    label = decision.outcome.replace("_", " ")
    message = f"Decision recorded: {label}." + (" Existing record reused." if reused else "")
    return RedirectResponse(url=f"/dashboard/verifications?message={quote(message)}", status_code=303)
