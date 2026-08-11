"""Explainable checks for Phase 10 execution verification."""

from fastapi import HTTPException

from app import models, schemas


def confirmation_values(review: schemas.ExecutionVerificationCreate) -> dict[str, bool]:
    return {
        "correct_client_confirmed": review.correct_client_confirmed,
        "approved_task_followed": review.approved_task_followed,
        "output_exists": review.output_exists,
        "result_matches_requested_outcome": review.result_matches_requested_outcome,
        "no_unexpected_changes": review.no_unexpected_changes,
    }


def evaluate_execution(
    task: models.Task,
    execution: models.FulfillmentExecution,
    review: schemas.ExecutionVerificationCreate,
    approval_exists: bool,
    content_review_approved: bool = True,
) -> dict[str, bool]:
    """Combine saved facts with explicit human confirmations."""
    evidence = execution.evidence or {}
    actions = execution.intended_actions or []
    tests = execution.simulated_test_results or []
    requested_outcome_recorded = any(task.requested_outcome in action for action in actions)
    output_reference_exists = bool(
        execution.simulated_changed_files
        or evidence.get("output_url")
        or evidence.get("external_id")
    )
    evidence_present = bool(
        evidence.get("summary")
        and evidence.get("task_id")
        and evidence.get("client_id")
    )
    acceptance_contract_present = bool(
        str(task.expected_result or "").strip()
        and str(task.success_metric or "").strip()
        and str(task.verification_window or "").strip()
    )
    correct_client = bool(
        review.correct_client_confirmed
        and execution.client_id == task.client_id
        and evidence.get("client_id") == task.client_id
        and evidence.get("task_id") == task.id
    )
    return {
        "correct_client": correct_client,
        "approval_exists": approval_exists,
        "approved_task_followed": bool(
            review.approved_task_followed and approval_exists and requested_outcome_recorded
        ),
        "output_exists": bool(review.output_exists and output_reference_exists),
        "tests_present": bool(tests),
        "tests_passed": bool(tests and all(item.get("status") == "passed" for item in tests)),
        "evidence_present": evidence_present,
        "acceptance_contract_present": acceptance_contract_present,
        "content_review_approved": content_review_approved,
        "result_matches_requested_outcome": bool(
            review.result_matches_requested_outcome and requested_outcome_recorded
        ),
        "no_unexpected_changes": review.no_unexpected_changes,
    }


def validate_requested_outcome(outcome: str, results: dict[str, bool]) -> None:
    """Prevent a human label from contradicting the saved execution facts."""
    verification_checks = [
        "correct_client",
        "approval_exists",
        "approved_task_followed",
        "output_exists",
        "tests_present",
        "tests_passed",
        "evidence_present",
        "acceptance_contract_present",
        "content_review_approved",
        "result_matches_requested_outcome",
        "no_unexpected_changes",
    ]
    hard_failure_checks = [
        "correct_client",
        "approval_exists",
        "approved_task_followed",
        "acceptance_contract_present",
        "content_review_approved",
        "tests_passed",
        "result_matches_requested_outcome",
        "no_unexpected_changes",
    ]
    insufficient_checks = ["output_exists", "tests_present", "evidence_present", "acceptance_contract_present"]

    if outcome == "verified" and not all(results[name] for name in verification_checks):
        failed = [name for name in verification_checks if not results[name]]
        raise HTTPException(
            status_code=409,
            detail=f"Execution cannot be verified; failed checks: {', '.join(failed)}",
        )
    if outcome == "verification_failed" and all(results[name] for name in hard_failure_checks):
        raise HTTPException(
            status_code=409,
            detail="Use verification_failed only when a scope, client, test, or outcome check failed",
        )
    if outcome == "not_enough_evidence" and all(results[name] for name in insufficient_checks):
        raise HTTPException(
            status_code=409,
            detail="Use not_enough_evidence only when output, tests, or execution evidence is missing",
        )
