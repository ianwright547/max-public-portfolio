"""Replaceable fake fulfillment executor for Phase 8.

This module never imports or calls an external execution tool. The route owns
authorization and persistence; this service only creates a deterministic fake
result from an already-authorized task.
"""

from dataclasses import dataclass
from typing import Optional

from app import models, schemas


RETRY_DELAYS_SECONDS = [10, 60, 300]


@dataclass(frozen=True)
class FakeExecutionResult:
    status: str
    intended_actions: list[str]
    simulated_changed_files: list[str]
    simulated_test_results: list[dict]
    evidence: dict
    attempt_count: int
    retry_delays_seconds: list[int]
    failure_type: Optional[str]
    error_message: Optional[str]


class FakeFulfillmentExecutor:
    """Generate a visible fake result without touching a client system."""

    name = "fake_fulfillment_executor"

    def execute(
        self,
        task: models.Task,
        request: schemas.SimulatedExecutionCreate,
    ) -> FakeExecutionResult:
        if request.outcome == "failure" and request.failure_type is None:
            raise ValueError("A failure type is required for a failed demo")
        if request.outcome != "failure" and request.failure_type is not None:
            raise ValueError("Failure type is only valid for a failed demo")
        if request.outcome == "blocked" and request.temporary_failures_before_result:
            raise ValueError("A blocked demo cannot retry")

        intended_actions = [
            "Read the approved task instructions",
            f"Simulate the requested outcome: {task.requested_outcome}",
            "Run simulated checks and save evidence",
        ]

        if request.outcome == "success":
            retry_delays = RETRY_DELAYS_SECONDS[: request.temporary_failures_before_result]
            return FakeExecutionResult(
                status="completed",
                intended_actions=intended_actions,
                simulated_changed_files=["simulation/client-site/example-change.txt"],
                simulated_test_results=[
                    {"name": "simulated task check", "status": "passed", "simulated": True}
                ],
                evidence={
                    "executor": self.name,
                    "simulated": True,
                    "summary": "The requested outcome was completed in demo mode only.",
                },
                attempt_count=1 + len(retry_delays),
                retry_delays_seconds=retry_delays,
                failure_type=None,
                error_message=None,
            )

        if request.outcome == "blocked":
            return FakeExecutionResult(
                status="blocked",
                intended_actions=intended_actions,
                simulated_changed_files=[],
                simulated_test_results=[
                    {"name": "simulated task check", "status": "not_run", "simulated": True}
                ],
                evidence={
                    "executor": self.name,
                    "simulated": True,
                    "summary": "The demo stopped before making a simulated change.",
                },
                attempt_count=1,
                retry_delays_seconds=[],
                failure_type=None,
                error_message="Simulated required access was unavailable",
            )

        temporary = request.failure_type == "temporary"
        retry_delays = RETRY_DELAYS_SECONDS if temporary else []
        return FakeExecutionResult(
            status="failed",
            intended_actions=intended_actions,
            simulated_changed_files=[],
            simulated_test_results=[
                {"name": "simulated task check", "status": "failed", "simulated": True}
            ],
            evidence={
                "executor": self.name,
                "simulated": True,
                "summary": "The fake executor did not complete the requested outcome.",
            },
            attempt_count=1 + len(retry_delays),
            retry_delays_seconds=retry_delays,
            failure_type=request.failure_type,
            error_message=f"Simulated {request.failure_type} failure",
        )
