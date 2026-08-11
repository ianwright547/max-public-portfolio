"""Small deterministic rules used by Phase 6 health checks.

This file has no database or HTTP code. Changing a threshold should require
editing one obvious constant or rule, and the same input always gives the same
result.
"""

from dataclasses import dataclass
from typing import Any


MAJOR_DECLINE_PERCENT = -25.0
DECLINE_METRICS = {
    "calls",
    "website_clicks",
    "direction_requests",
    "impressions",
    "search_clicks",
}
BAD_CONNECTION_STATUSES = {"missing_permission", "error", "disconnected"}


@dataclass(frozen=True)
class ProposedFinding:
    rule_key: str
    title: str
    explanation: str
    evidence: dict[str, Any]
    source: str
    severity: str
    confidence: str
    recommended_action: str


def evaluate_health(
    website_status: str,
    intake_domain: str,
    has_intake: bool,
    integrations: list[dict[str, Any]],
    metric_comparisons: list[dict[str, Any]],
) -> tuple[str, str, list[ProposedFinding]]:
    """Evaluate current evidence without guessing or contacting external tools."""
    findings: list[ProposedFinding] = []

    if website_status == "unavailable":
        findings.append(
            ProposedFinding(
                rule_key="website_unavailable",
                title="Website unavailable",
                explanation="The website was manually reported as unavailable during this check.",
                evidence={"domain": intake_domain or None, "observed_status": "unavailable"},
                source="manual_website_check",
                severity="critical",
                confidence="high",
                recommended_action="Confirm the outage, then restore the website or contact the hosting provider.",
            )
        )

    for integration in integrations:
        connection_status = str(integration["connection_status"])
        if connection_status not in BAD_CONNECTION_STATUSES:
            continue
        name = str(integration["integration_name"])
        findings.append(
            ProposedFinding(
                rule_key=f"integration_access:{integration['id']}",
                title=f"{name} access needs attention",
                explanation="The saved integration status says Max cannot reliably use this data source.",
                evidence={
                    "integration_id": integration["id"],
                    "connection_status": connection_status,
                    "issues": integration.get("issues", []),
                },
                source="saved_integration_status",
                severity="warning",
                confidence="high",
                recommended_action="Review the saved error and restore the required permission or connection.",
            )
        )

    for comparison in metric_comparisons:
        metric_name = str(comparison["metric_name"])
        percent = comparison.get("percent_change")
        if metric_name not in DECLINE_METRICS or percent is None or percent > MAJOR_DECLINE_PERCENT:
            continue
        source_type = str(comparison["source_type"])
        findings.append(
            ProposedFinding(
                rule_key=f"metric_decline:{metric_name}",
                title=f"{metric_name.replace('_', ' ').title()} declined",
                explanation=(
                    f"The latest saved value is {abs(float(percent)):.1f}% lower than the previous period. "
                    "This identifies a change, not its cause."
                ),
                evidence={
                    "metric_name": metric_name,
                    "previous_period": comparison["previous_period"],
                    "previous_value": comparison["previous_value"],
                    "current_period": comparison["current_period"],
                    "current_value": comparison["current_value"],
                    "percent_change": percent,
                    "source_type": source_type,
                },
                source=f"metric_snapshot:{source_type}",
                severity="warning",
                confidence="medium" if source_type == "mock" else "high",
                recommended_action="Review the metric and its source, then investigate likely causes before proposing work.",
            )
        )

    missing_reasons = []
    if not has_intake:
        missing_reasons.append("No onboarding intake is saved")
    elif not intake_domain:
        missing_reasons.append("No website domain is saved")
    if website_status == "unknown":
        missing_reasons.append("Website availability has not been checked")
    if not metric_comparisons:
        missing_reasons.append("No metric has two comparable periods")

    if missing_reasons:
        findings.append(
            ProposedFinding(
                rule_key="not_enough_core_data",
                title="Not enough information for a complete health check",
                explanation="Max is missing evidence required to make a reliable healthy-or-unhealthy judgment.",
                evidence={"missing": missing_reasons},
                source="health_check_requirements",
                severity="information",
                confidence="high",
                recommended_action="Add the missing information, then run the health check again.",
            )
        )

    severities = {finding.severity for finding in findings}
    if "critical" in severities:
        return "critical", "A critical issue requires review.", findings
    if "warning" in severities:
        return "needs_attention", "One or more evidence-backed issues need attention.", findings
    if missing_reasons:
        return "not_enough_data", "More information is required before Max can judge client health.", findings
    return "healthy", "No meaningful issue was detected. No action is needed.", findings
