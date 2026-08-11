"""Allowlisted actions initiated by signed Slack mentions in cleared channels."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import os
import re

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.audit import record_event
from app.client_lifecycle_service import disable_client_jobs


CLIENT_STATUSES = {
    "onboarding",
    "awaiting_profile_approval",
    "planning",
    "awaiting_plan_approval",
    "fulfillment_in_progress",
    "awaiting_website_approval",
    "active",
    "paused",
    "cancelled",
}


@dataclass(frozen=True)
class SlackOwnerAction:
    action_type: str
    target_status: str | None = None
    source_status: str | None = None
    all_current_clients: bool = False
    business_name: str | None = None
    service_start_date: date | None = None
    task_id: str | None = None
    task_target_status: str | None = None
    report_id: str | None = None
    gbp_post_id: str | None = None
    gbp_post_payload: dict | None = None
    gbp_post_parse_error: str | None = None
    profile_version_id: str | None = None
    connection_candidate_id: str | None = None
    execution_id: str | None = None
    packet_id: str | None = None
    daily_plan_item_index: int | None = None
    codex_result_payload: dict | None = None
    codex_result_parse_error: str | None = None
    content_review_payload: dict | None = None
    content_review_parse_error: str | None = None
    target_url: str | None = None
    instructions: str | None = None
    mode: str | None = None
    seo_work_type: str | None = None
    notification_id: str | None = None
    website_status: str | None = None
    window_days: int | None = None
    requested_outcome: str | None = None
    reason: str | None = None
    risk: str | None = None
    workflow: str | None = None
    workflow_depth: str | None = None
    workflow_focus: str | None = None
    workflow_create_tasks: bool = False
    enabled: bool | None = None
    intake_payload: dict | None = None
    intake_parse_error: str | None = None
    connection_type: str | None = None
    connection_payload: dict | None = None
    connection_parse_error: str | None = None
    client_update_payload: dict | None = None
    client_update_parse_error: str | None = None
    metric_payload: dict | None = None
    metric_parse_error: str | None = None
    outcome_payload: dict | None = None
    outcome_parse_error: str | None = None
    report_payload: dict | None = None
    report_parse_error: str | None = None
    profile_correction_payload: dict | None = None
    profile_correction_parse_error: str | None = None
    memory_id: str | None = None
    memory_content: str | None = None
    memory_category: str | None = None


@dataclass(frozen=True)
class SlackOwnerActionResult:
    text: str
    changed_client_ids: tuple[str, ...]
    archive_channel_id: str | None = None


def detect_owner_action(question: str, *, has_mapped_client: bool) -> SlackOwnerAction | None:
    """Recognize explicit client lifecycle changes without granting arbitrary SQL access."""
    normalized = " ".join(question.lower().split())
    if normalized in {"help", "commands", "show commands", "what can you do", "what can you do?"}:
        return SlackOwnerAction(action_type="show_help")
    if re.search(r"\b(?:what do you remember|show (?:my )?memories|list (?:my )?memories)\b", normalized):
        return SlackOwnerAction(action_type="list_memories")
    # Question-shaped wording needs semantic classification so hypotheticals such
    # as "what happens if we remove this client?" never trigger a substring match.
    if re.match(
        r"^(?:what|why|how|when|where|would|could|should|can|do|does|did|is|are|if|suppose|imagine|hypothetically)\b",
        normalized,
    ):
        return None
    if re.search(r"\b(?:don't|dont|do not|never|not to)\b", normalized):
        return None
    forget_memory = re.search(
        r"\bforget\s+(?:memory\s+)?(slack_memory_[a-z0-9]+)\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if forget_memory:
        return SlackOwnerAction(action_type="forget_memory", memory_id=forget_memory.group(1))
    update_memory = re.search(
        r"\bupdate\s+memory\s+(slack_memory_[a-z0-9]+)\s+(?:to|with)\s+(.+)",
        question,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if update_memory:
        return SlackOwnerAction(
            action_type="update_memory",
            memory_id=update_memory.group(1),
            memory_content=update_memory.group(2).strip(" ."),
        )
    style_memory = re.search(
        r"\b(?:remember|set|update|change|learn)\b.*?\b(?:style|tone|responses?)\b(?:\s+(?:to|as)|\s*[:,-])\s*(.+)",
        question,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if style_memory:
        return SlackOwnerAction(
            action_type="save_memory",
            memory_content=style_memory.group(1).strip(" ."),
            memory_category="style",
        )
    remember_memory = re.search(
        r"^\s*remember(?:\s+(?:that|this))?\s*[:,-]?\s*(.*)$",
        question,
        flags=re.IGNORECASE | re.DOTALL,
    )
    store_memory = re.search(
        r"^\s*(?:store|save)(?:\s+this)?\s+(?:in|to)\s+memory\s*[:,-]?\s*(.*)$",
        question,
        flags=re.IGNORECASE | re.DOTALL,
    )
    memory_match = remember_memory or store_memory
    if memory_match:
        content = memory_match.group(1).strip(" .") or None
        category = (
            "preference"
            if content and re.search(r"\b(?:prefer|preference|always|never)\b", content, re.IGNORECASE)
            else "general"
        )
        return SlackOwnerAction(
            action_type="save_memory",
            memory_content=content,
            memory_category=category,
        )
    prepare_content = re.search(
        r"\bprepare\s+(?:a\s+)?(?:content|seo)\s+task\s+(task_[a-z0-9]+)(?:\s+(?:as|for)\s+(local_page|local page|blog|article))?\b",
        question,
        flags=re.IGNORECASE,
    )
    if prepare_content:
        work_type = (prepare_content.group(2) or "local_page").casefold().replace(" ", "_")
        if work_type == "article":
            work_type = "blog"
        return SlackOwnerAction(
            action_type="prepare_content_task",
            task_id=prepare_content.group(1),
            mode="improve",
            seo_work_type=work_type,
        )

    daily_language = re.search(
        r"\b(?:daily|today|today's)\b.*\b(?:plan|tasks?|priorit(?:y|ies))\b|\b(?:plan|tasks?|priorit(?:y|ies))\b.*\b(?:daily|today|today's)\b",
        normalized,
    )
    convert_plan_item = re.search(
        r"\b(?:create|make|turn|convert)\s+(?:a\s+)?task\s+(?:from|for)\s+(?:the\s+)?(?:daily\s+plan\s+)?(?:recommendation|item)\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b",
        normalized,
    )
    if convert_plan_item and has_mapped_client:
        item_token = convert_plan_item.group(1).casefold()
        item_number = int(item_token) if item_token.isdigit() else {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        }[item_token]
        return SlackOwnerAction(
            action_type="convert_daily_plan_item",
            daily_plan_item_index=item_number - 1 if item_number > 0 else -1,
        )
    seo_plan_language = re.search(
        r"\b(?:seo|ranking|organic search)\b.*\b(?:plan|roadmap|priorit(?:y|ies)|tasks?)\b|\b(?:plan|roadmap)\b.*\b(?:seo|ranking|organic search)\b",
        normalized,
    )
    fulfillment_plan_language = re.search(
        r"\bfulfillment\b.*\b(?:plan|queue|tasks?|priorit(?:y|ies))\b",
        normalized,
    )
    workflow_language = re.search(
        r"\b(?:enable|disable|turn\s+(?:on|off))\b.*\b(?:daily\s+plans?|daily\s+planning)\b",
        normalized,
    )
    if (daily_language and not workflow_language) or seo_plan_language or fulfillment_plan_language:
        focus = (
            "seo"
            if seo_plan_language or "seo" in normalized or "ranking" in normalized
            else "fulfillment"
            if fulfillment_plan_language or "fulfillment" in normalized
            else "reporting"
            if "report" in normalized or "metric" in normalized
            else "all"
        )
        depth = (
            "in_depth"
            if seo_plan_language
            or re.search(r"\b(?:in[- ]?depth|deep|detailed|comprehensive|fresh|live)\b", normalized)
            else "simple"
        )
        return SlackOwnerAction(action_type="generate_daily_plan", mode=depth, workflow=focus)
    if has_mapped_client and re.search(
        r"\b(?:scrape|crawl)\b.*\b(?:website|site|pages?)\b|\binspect\b.*\b(?:website|site)\b|\b(?:website|site)\b.*\b(?:scrape|crawl|inspect)\b",
        normalized,
    ):
        return SlackOwnerAction(action_type="generate_client_update", mode="in_depth")
    report_language = re.search(r"\b(?:report|update|audit|overview)\b", normalized)
    portfolio_scope = re.search(r"\b(?:all|every)\s+clients?\b|\bportfolio\b", normalized)
    client_scope = has_mapped_client and re.search(
        r"\b(?:this|the)\s+client\b|\bclient\s+(?:report|update|audit|overview)\b",
        normalized,
    )
    if report_language and (portfolio_scope or client_scope):
        depth = (
            "in_depth"
            if re.search(r"\b(?:in[- ]?depth|deep|detailed|comprehensive|fresh|live)\b", normalized)
            else "simple"
        )
        return SlackOwnerAction(action_type="generate_client_update", mode=depth)
    if re.search(r"\b(?:add|create|onboard)\b", normalized) and re.search(
        r"\b(?:new\s+)?client\b", normalized
    ):
        business_name = _client_name_from_request(question)
        date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", question)
        service_start = None
        if date_match:
            try:
                service_start = date.fromisoformat(date_match.group(1))
            except ValueError:
                service_start = None
        starts_active = bool(
            re.search(
                r"\b(?:already active|skip onboarding|passed? onboarding|past onboarding)\b",
                normalized,
            )
        )
        return SlackOwnerAction(
            action_type="create_client",
            target_status="active" if starts_active else "onboarding",
            business_name=business_name,
            service_start_date=service_start,
        )

    task_decision = re.search(
        r"\b(approve|reject)\s+(?:the\s+|this\s+)?task(?:\s+(task_[a-z0-9]+))?\b(?:\s+(?:because|reason)\s+(.+))?",
        question,
        flags=re.IGNORECASE,
    )
    if task_decision:
        decision = "approved" if task_decision.group(1).lower() == "approve" else "rejected"
        reason = (task_decision.group(3) or "").strip(" .") or None
        return SlackOwnerAction(
            action_type="decide_task",
            target_status=decision,
            task_id=task_decision.group(2),
            reason=reason,
        )

    # In a mapped client channel, the owner may approve the single task Max
    # just presented without repeating its opaque ID. Selection remains
    # conservative: _decide_task still refuses when there is more than one
    # proposed task in scope.
    implicit_task_approval = re.match(
        r"^(?:approve\s+(?:this|it)|yes\s+approve|go\s+ahead(?:\s+with\s+it)?|proceed)[.!]?$",
        normalized,
    )
    if implicit_task_approval and has_mapped_client:
        return SlackOwnerAction(action_type="decide_task", target_status="approved")

    task_status = re.search(
        r"\b(?:retry|reset)\s+task\s+(task_[a-z0-9]+)\b|\bmark\s+task\s+(task_[a-z0-9]+)\s+(blocked|ready|running|completed|failed|verified)\b(?:\s+(?:because|reason)\s+(.+))?",
        question,
        flags=re.IGNORECASE,
    )
    if task_status:
        task_id = task_status.group(1) or task_status.group(2)
        target_status = "ready" if task_status.group(1) else task_status.group(3).lower()
        reason = (task_status.group(4) or "").strip(" .") or None
        return SlackOwnerAction(
            action_type="change_task_status",
            task_id=task_id,
            task_target_status=target_status,
            reason=reason,
        )

    task_request = re.search(
        r"\b(?:create|add|propose)\s+(?:a\s+)?(?:new\s+)?task\s+(?:to|for)\s+(.+)",
        question,
        flags=re.IGNORECASE,
    )
    if task_request and has_mapped_client:
        requested_outcome = task_request.group(1).strip(" .")
        risk_match = re.search(r"\b(low|medium|high)[ -]risk\b", requested_outcome, flags=re.IGNORECASE)
        risk = risk_match.group(1).lower() if risk_match else "medium"
        return SlackOwnerAction(
            action_type="propose_task",
            requested_outcome=requested_outcome[:1200],
            risk=risk,
        )

    onboarding_request = re.search(
        r"\b(?:start|resume|retry|queue)\s+(?:the\s+)?onboarding(?:\s+automation)?\b",
        normalized,
    )
    if onboarding_request and has_mapped_client:
        return SlackOwnerAction(action_type="queue_onboarding")

    website_generation_request = re.search(
        r"\b(?:request|start|create)\s+(?:a\s+)?website\s+generation(?:\s+task)?(?:\s+(?:as|in)\s+(new_build|new build|replicate|improve))?\b",
        question,
        flags=re.IGNORECASE,
    )
    if website_generation_request and has_mapped_client:
        mode = (website_generation_request.group(1) or "replicate").lower().replace(" ", "_")
        return SlackOwnerAction(action_type="request_website_generation", mode=mode)

    if re.search(r"\bsubmit\s+intake\b", normalized) and has_mapped_client:
        payload_match = re.search(r"\bsubmit\s+intake\s*(\{.*\})\s*$", question, flags=re.IGNORECASE | re.DOTALL)
        if payload_match is None:
            return SlackOwnerAction(
                action_type="submit_intake",
                intake_parse_error="Use `submit intake {JSON}` with the required fields shown by `@Max help`.",
            )
        try:
            payload = json.loads(payload_match.group(1))
        except json.JSONDecodeError:
            return SlackOwnerAction(action_type="submit_intake", intake_parse_error="The intake JSON is invalid.")
        if not isinstance(payload, dict):
            return SlackOwnerAction(action_type="submit_intake", intake_parse_error="The intake payload must be a JSON object.")
        return SlackOwnerAction(action_type="submit_intake", intake_payload=payload)

    connection_request = re.search(
        r"\bconnect\s+(website|github|search\s+console|google\s+business\s+profile|gbp)\s*(\{.*\})\s*$",
        question,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if connection_request and has_mapped_client:
        connection_type = connection_request.group(1).lower().replace(" ", "_")
        if connection_type == "gbp":
            connection_type = "google_business_profile"
        try:
            payload = json.loads(connection_request.group(2))
        except json.JSONDecodeError:
            return SlackOwnerAction(
                action_type="connect_integration",
                connection_type=connection_type,
                connection_parse_error="The connection JSON is invalid.",
            )
        if not isinstance(payload, dict):
            return SlackOwnerAction(
                action_type="connect_integration",
                connection_type=connection_type,
                connection_parse_error="The connection payload must be a JSON object.",
            )
        return SlackOwnerAction(
            action_type="connect_integration",
            connection_type=connection_type,
            connection_payload=payload,
        )

    client_update = re.search(
        r"\bupdate\s+client\s*(\{.*\})\s*$",
        question,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if client_update and has_mapped_client:
        try:
            payload = json.loads(client_update.group(1))
        except json.JSONDecodeError:
            return SlackOwnerAction(action_type="update_client", client_update_parse_error="The client update JSON is invalid.")
        if not isinstance(payload, dict):
            return SlackOwnerAction(action_type="update_client", client_update_parse_error="The client update must be a JSON object.")
        return SlackOwnerAction(action_type="update_client", client_update_payload=payload)
    if re.search(
        r"\b(?:delete|remove)\s+(?:this\s+|the\s+|a\s+)?(?:client|cleint)\b",
        normalized,
    ) and has_mapped_client:
        return SlackOwnerAction(action_type="delete_client")
    if re.search(r"\b(?:archive|close)\s+(?:this\s+)?client\b", normalized) and has_mapped_client:
        return SlackOwnerAction(action_type="archive_client")

    if re.search(r"\b(?:show|check|what(?:'s| is)?)\s+(?:the\s+)?(?:intake|onboarding)\s+(?:status|details|requirements|gaps)\b", normalized) and has_mapped_client:
        return SlackOwnerAction(action_type="intake_status")

    metric_request = re.search(
        r"\brecord\s+metric\s*(\{.*\})\s*$",
        question,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if metric_request and has_mapped_client:
        try:
            payload = json.loads(metric_request.group(1))
        except json.JSONDecodeError:
            return SlackOwnerAction(action_type="record_metric", metric_parse_error="The metric JSON is invalid.")
        if not isinstance(payload, dict):
            return SlackOwnerAction(action_type="record_metric", metric_parse_error="The metric payload must be a JSON object.")
        return SlackOwnerAction(action_type="record_metric", metric_payload=payload)

    outcome_request = re.search(
        r"\b(?:record|save|log)\s+(?:the\s+)?(?:outcome|result)\s+(?:for|of)\s+(?:task\s+)?(task_[a-z0-9]+)\s*(\{.*\})\s*$",
        question,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if outcome_request and has_mapped_client:
        try:
            payload = json.loads(outcome_request.group(2))
        except json.JSONDecodeError:
            return SlackOwnerAction(
                action_type="record_outcome",
                task_id=outcome_request.group(1),
                outcome_parse_error="The outcome JSON is invalid.",
            )
        if not isinstance(payload, dict):
            return SlackOwnerAction(
                action_type="record_outcome",
                task_id=outcome_request.group(1),
                outcome_parse_error="The outcome payload must be a JSON object.",
            )
        return SlackOwnerAction(
            action_type="record_outcome",
            task_id=outcome_request.group(1),
            outcome_payload=payload,
        )

    report_request = re.search(
        r"\bcreate\s+report\s*(\{.*\})\s*$",
        question,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if report_request and has_mapped_client:
        try:
            payload = json.loads(report_request.group(1))
        except json.JSONDecodeError:
            return SlackOwnerAction(action_type="create_report", report_parse_error="The report JSON is invalid.")
        if not isinstance(payload, dict):
            return SlackOwnerAction(action_type="create_report", report_parse_error="The report payload must be a JSON object.")
        return SlackOwnerAction(action_type="create_report", report_payload=payload)

    gbp_post_request = re.search(
        r"\b(?:create|draft)\s+(?:a\s+)?(?:google\s+business\s+profile|gbp)\s+post\s*(\{.*\})\s*$",
        question,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if gbp_post_request and has_mapped_client:
        try:
            payload = json.loads(gbp_post_request.group(1))
        except json.JSONDecodeError:
            return SlackOwnerAction(
                action_type="create_gbp_post",
                gbp_post_parse_error="The GBP post JSON is invalid.",
            )
        if not isinstance(payload, dict):
            return SlackOwnerAction(
                action_type="create_gbp_post",
                gbp_post_parse_error="The GBP post payload must be a JSON object.",
            )
        return SlackOwnerAction(action_type="create_gbp_post", gbp_post_payload=payload)

    gbp_post_action = re.search(
        r"\b(approve|publish)\s+(?:the\s+)?(?:google\s+business\s+profile\s+|gbp\s+)?post\s+(gbp_post_[a-z0-9]+)\b",
        question,
        flags=re.IGNORECASE,
    )
    if gbp_post_action:
        return SlackOwnerAction(
            action_type="approve_gbp_post" if gbp_post_action.group(1).lower() == "approve" else "publish_gbp_post",
            gbp_post_id=gbp_post_action.group(2),
        )

    workflow_action = re.search(
        r"\b(enable|disable|turn\s+(?:on|off))\s+(?:(in[- ]?depth|deep|simple)\s+)?(?:the\s+)?(health\s+checks?|website\s+analytics|website\s+metrics|search\s+console|daily\s+plans?|daily\s+planning)\b(?:\s+with\s+(tasks|approval\s+tasks))?",
        normalized,
    )
    if workflow_action and has_mapped_client:
        verb = workflow_action.group(1)
        enabled = verb == "enable" or verb == "turn on"
        requested_depth = workflow_action.group(2)
        workflow = workflow_action.group(3).replace(" ", "_")
        create_tasks = bool(workflow_action.group(4))
        if workflow.startswith("health_check"):
            workflow = "health_check"
        elif workflow in {"website_analytics", "website_metrics"}:
            workflow = "website_metrics_sync"
        elif workflow in {"daily_plans", "daily_plan", "daily_planning"}:
            workflow = "daily_client_plan"
        else:
            workflow = "search_console_sync"
        return SlackOwnerAction(
            action_type="set_workflow",
            workflow=workflow,
            enabled=enabled,
            workflow_depth=("in_depth" if requested_depth and requested_depth != "simple" else "simple") if workflow == "daily_client_plan" else None,
            workflow_create_tasks=create_tasks if workflow == "daily_client_plan" else False,
        )

    report_action = re.search(
        r"\b(approve|send|deliver)\s+(?:the\s+|this\s+)?report(?:\s+(report_[a-z0-9]+))?\b",
        question,
        flags=re.IGNORECASE,
    )
    if report_action:
        verb = report_action.group(1).lower()
        return SlackOwnerAction(
            action_type="approve_report" if verb == "approve" else "deliver_report",
            report_id=report_action.group(2),
        )

    profile_action = re.search(
        r"\b(approve|reject)\s+(?:the\s+|this\s+)?profile(?:\s+(profile_version_[a-z0-9]+))?\b(?:\s+(?:because|reason)\s+(.+))?",
        question,
        flags=re.IGNORECASE,
    )
    if profile_action:
        return SlackOwnerAction(
            action_type="decide_profile",
            target_status=profile_action.group(1).lower(),
            profile_version_id=profile_action.group(2),
            reason=(profile_action.group(3) or "").strip(" .") or None,
        )

    profile_correction = re.search(
        r"\bcorrect\s+profile\s+(profile_version_[a-z0-9]+)\s+(?:with\s+)?(\{.*\})\s*$",
        question,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if profile_correction:
        try:
            payload = json.loads(profile_correction.group(2))
        except json.JSONDecodeError:
            return SlackOwnerAction(action_type="correct_profile", profile_version_id=profile_correction.group(1), profile_correction_parse_error="The profile correction JSON is invalid.")
        if not isinstance(payload, dict):
            return SlackOwnerAction(action_type="correct_profile", profile_version_id=profile_correction.group(1), profile_correction_parse_error="The profile correction must be a JSON object.")
        return SlackOwnerAction(action_type="correct_profile", profile_version_id=profile_correction.group(1), profile_correction_payload=payload)

    connection_action = re.search(
        r"\b(approve|reject)\s+(?:the\s+|this\s+)?(?:connection\s+)?candidate\s+(candidate_[a-z0-9]+)\b(?:\s+(?:because|reason)\s+(.+))?",
        question,
        flags=re.IGNORECASE,
    )
    if connection_action:
        return SlackOwnerAction(
            action_type="decide_connection_candidate",
            target_status=connection_action.group(1).lower(),
            connection_candidate_id=connection_action.group(2),
            reason=(connection_action.group(3) or "").strip(" .") or None,
        )

    codex_result = re.search(
        r"\b(?:record|save|submit)\s+(?:the\s+)?codex\s+result\s+(?:for\s+)?(?:packet\s+)?(packet_[a-z0-9]+)\s+(\{.*\})\s*$",
        question,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if codex_result:
        try:
            payload = json.loads(codex_result.group(2))
        except json.JSONDecodeError:
            return SlackOwnerAction(
                action_type="record_codex_result",
                packet_id=codex_result.group(1),
                codex_result_parse_error="The Codex result JSON is invalid.",
            )
        if not isinstance(payload, dict):
            return SlackOwnerAction(
                action_type="record_codex_result",
                packet_id=codex_result.group(1),
                codex_result_parse_error="The Codex result must be a JSON object.",
            )
        return SlackOwnerAction(
            action_type="record_codex_result",
            packet_id=codex_result.group(1),
            codex_result_payload=payload,
        )

    content_review = re.search(
        r"\b(?:approve|record)\s+(?:the\s+)?content\s+review\s+(?:for\s+)?(?:packet\s+)?(packet_[a-z0-9]+)\s+(\{.*\})\s*$",
        question,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if content_review:
        try:
            payload = json.loads(content_review.group(2))
        except json.JSONDecodeError:
            return SlackOwnerAction(
                action_type="record_content_review",
                packet_id=content_review.group(1),
                content_review_parse_error="The content-review JSON is invalid.",
            )
        if not isinstance(payload, dict):
            return SlackOwnerAction(
                action_type="record_content_review",
                packet_id=content_review.group(1),
                content_review_parse_error="The content-review payload must be a JSON object.",
            )
        return SlackOwnerAction(
            action_type="record_content_review",
            packet_id=content_review.group(1),
            content_review_payload=payload,
        )

    codex_packet_action = re.search(
        r"\b(show|copy|handoff|hand\s+off)\s+(?:the\s+)?(?:codex\s+)?packet\s+(packet_[a-z0-9]+)\b",
        question,
        flags=re.IGNORECASE,
    )
    if codex_packet_action:
        return SlackOwnerAction(
            action_type=("handoff_codex_packet" if codex_packet_action.group(1).casefold().replace(" ", "") in {"handoff"} else "show_codex_packet"),
            packet_id=codex_packet_action.group(2),
        )

    prepare_website = re.search(
        r"\bprepare\s+(?:a\s+)?website\s+task\s+(task_[a-z0-9]+)(?:\s+(?:as|in)\s+(new_build|new build|replicate|improve|repair))?\b",
        question,
        flags=re.IGNORECASE,
    )
    if prepare_website:
        mode = (prepare_website.group(2) or "improve").lower().replace(" ", "_")
        return SlackOwnerAction(
            action_type="prepare_website_task",
            task_id=prepare_website.group(1),
            mode=mode,
        )

    run_website = re.search(
        r"\b(?:run|generate|execute)\s+(?:the\s+)?website\s+task\s+(task_[a-z0-9]+)(?:\s+(?:using|with)\s+(?:packet\s+)?(packet_[a-z0-9]+))?\b",
        question,
        flags=re.IGNORECASE,
    )
    if run_website:
        return SlackOwnerAction(
            action_type="run_website_task",
            task_id=run_website.group(1),
            packet_id=run_website.group(2),
        )

    run_browser = re.search(
        r"\b(?:run|execute|use)\s+(?:the\s+)?browser\s+(?:for\s+)?task\s+(task_[a-z0-9]+)\s+(?:at|on)\s+(https://\S+?)\s+(?:to|and)\s+(.+)",
        question,
        flags=re.IGNORECASE,
    )
    if run_browser:
        return SlackOwnerAction(
            action_type="run_browser_task",
            task_id=run_browser.group(1),
            target_url=run_browser.group(2).rstrip(".,"),
            instructions=run_browser.group(3).strip(" .")[:4000],
        )

    poll_execution = re.search(
        r"\bpoll\s+(?:the\s+)?execution\s+(execution_[a-z0-9]+)\b",
        question,
        flags=re.IGNORECASE,
    )
    if poll_execution:
        return SlackOwnerAction(
            action_type="poll_execution",
            execution_id=poll_execution.group(1),
        )

    verify_execution = re.search(
        r"\b(confirm\s+)?(?:verify|review)\s+(?:the\s+)?execution\s+(execution_[a-z0-9]+)\b",
        question,
        flags=re.IGNORECASE,
    )
    if verify_execution:
        return SlackOwnerAction(
            action_type="verify_execution" if verify_execution.group(1) else "review_execution",
            execution_id=verify_execution.group(2),
        )

    health_check = re.search(
        r"\brun\s+(?:a\s+)?health\s+check(?:\s+(?:with\s+)?website\s+(available|unavailable|unknown))?\b",
        question,
        flags=re.IGNORECASE,
    )
    if health_check and has_mapped_client:
        return SlackOwnerAction(
            action_type="run_health_check",
            website_status=(health_check.group(1) or "unknown").lower(),
        )

    website_metrics = re.search(
        r"\bsync\s+(?:the\s+)?(?:website\s+)?metrics(?:\s+(?:for\s+)?(7|30|90)\s+days)?\b",
        question,
        flags=re.IGNORECASE,
    )
    if website_metrics:
        return SlackOwnerAction(
            action_type="sync_website_metrics",
            window_days=int(website_metrics.group(1) or 30),
        )

    if re.search(r"\bsync\s+(?:google\s+)?search\s+console\b", normalized) and has_mapped_client:
        return SlackOwnerAction(action_type="sync_search_console", window_days=28)

    notification_action = re.search(
        r"\b(mark|retry)\s+(?:the\s+)?notification\s+(notification_[a-z0-9]+)(?:\s+read)?\b",
        question,
        flags=re.IGNORECASE,
    )
    if notification_action:
        return SlackOwnerAction(
            action_type=(
                "mark_notification_read"
                if notification_action.group(1).lower() == "mark"
                else "retry_notification"
            ),
            notification_id=notification_action.group(2),
        )

    if re.search(r"\brun\s+(?:all\s+)?due\s+jobs\b", normalized):
        return SlackOwnerAction(action_type="run_due_jobs")

    action_words = r"(?:move|change|set|mark|advance|activate|pause|cancel)"
    if not re.search(rf"\b{action_words}\b", normalized):
        return None

    target_status = None
    source_status = None
    if re.search(r"\b(?:passed?|past|finished|completed|done with) onboarding\b", normalized):
        target_status = "active"
        source_status = "onboarding"
    else:
        aliases = {
            "active": "active",
            "paused": "paused",
            "pause": "paused",
            "cancelled": "cancelled",
            "canceled": "cancelled",
            "planning": "planning",
            "fulfillment": "fulfillment_in_progress",
            "website approval": "awaiting_website_approval",
            "plan approval": "awaiting_plan_approval",
            "profile approval": "awaiting_profile_approval",
        }
        for phrase, status in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
            if re.search(rf"\b{re.escape(phrase)}\b", normalized):
                target_status = status
                break
    if target_status not in CLIENT_STATUSES:
        return None

    all_current = bool(
        re.search(r"\b(?:all|every|these|them|current)\b", normalized)
        and re.search(r"\bclients?\b|\bthem\b|\bthese\b", normalized)
    )
    if not all_current and not has_mapped_client:
        return None
    return SlackOwnerAction(
        action_type="set_client_status",
        target_status=target_status,
        source_status=source_status,
        all_current_clients=all_current,
    )


def _client_name_from_request(question: str) -> str | None:
    named = re.search(
        r"\bclient\s+(?:named|called)\s+['\"]?(.+?)['\"]?(?:\s+(?:starting|with|on)\b|[.!?]|$)",
        question,
        flags=re.IGNORECASE,
    )
    if named:
        value = named.group(1).strip(" \t'\"")
        return value[:200] or None
    trailing = re.search(
        r"\b(?:add|create|onboard)\s+(?:a\s+)?(?:new\s+)?client\s+(.+)$",
        question,
        flags=re.IGNORECASE,
    )
    if trailing:
        value = trailing.group(1).strip(" \t.!?'\"")
        if value and not re.match(r"^(?:then|and|please|for me)\b", value, flags=re.IGNORECASE):
            value = re.split(r"\s+(?:starting|with start date|on)\s+20\d{2}-\d{2}-\d{2}\b", value)[0]
            return value[:200] or None
    return None


def apply_owner_action(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    """Execute one validated action and append an audit record for each changed client."""
    if action.action_type == "show_help":
        return SlackOwnerActionResult(
            text=(
                "*Slack controls available now*\n"
                "• Ask operational questions about clients, tasks, findings, onboarding, reports, and alerts.\n"
                "• `remember that ...` or `store this in memory: ...` to save a durable scoped memory\n"
                "• `update your response style to ...` to replace the saved style preference\n"
                "• `what do you remember?`, `update memory MEMORY_ID to ...`, or `forget memory MEMORY_ID`\n"
                "• `simple report on all clients` for a fast saved-data summary\n"
                "• `in-depth report on all clients` for fresh website, Search Console, analytics, GBP-access, and 30/60/90-day findings\n"
                "• In a client channel: `simple report for this client` or `in-depth audit for this client`\n"
                "• `daily plan for all clients` or, in a client channel, `today's tasks for this client`\n"
                "• In a client channel: `create a task from daily plan item 1` to turn a recommendation into an approval-required task; `enable in-depth daily plans with tasks` proposes all safe recommendations\n"
                "• `in-depth SEO plan for this client`, `fulfillment plan`, or `scrape this website`\n"
                "• `create a new client called BUSINESS NAME starting YYYY-MM-DD`\n"
                "• In a client channel: `create a task to REQUEST`\n"
                "• `approve task task_1234abcd`\n"
                "• `reject task task_1234abcd because REASON`\n"
                "• `retry task task_1234abcd` or `mark task task_1234abcd blocked because REASON`\n"
                "• In a client channel: `start onboarding`\n"
                "• In a client channel: `request website generation as replicate`\n"
                "• In a client channel: `submit intake {JSON}` with phone_number, email, brand_colors, domain, business_hours, service_areas, google_business_profile, enabled_workflows\n"
                "• In a client channel: `connect website|github|search console|gbp {JSON}` (links only; no credentials)\n"
                "• In a client channel: `show intake status` or `show onboarding gaps`\n"
                "• In a client channel: `record metric {JSON}` or `create report {JSON}`\n"
                "• In a client channel: `record outcome for task task_1234abcd {JSON}` with metric_name, assessment, source_reference, evidence, notes, recorded_by, and observed_at\n"
                "• In a client channel: `update client {JSON}`, `archive this client`, or `delete this client`\n"
                "• `approve profile profile_version_1234abcd`\n"
                "• `reject profile profile_version_1234abcd because REASON`\n"
                "• `correct profile profile_version_1234abcd with {JSON}` after rejection\n"
                "• `approve connection candidate candidate_1234567890`\n"
                "• `reject connection candidate candidate_1234567890 because REASON`\n"
                "• `approve report report_1234abcd` then `send report report_1234abcd`\n"
                "• In a client channel: `create GBP post {JSON}`, then `approve GBP post gbp_post_1234abcd` and `publish GBP post gbp_post_1234abcd`\n"
                "• `prepare website task task_1234abcd as improve`\n"
                "• `prepare content task task_1234abcd as local_page|blog` to create an evidence-backed Codex content brief\n"
                "• `show codex packet packet_1234abcd` to inspect its quality gate, or `handoff codex packet packet_1234abcd`\n"
                "• `record codex result packet_1234abcd {JSON}` with operation_key, outcome, submitted_by, summary, changed_files, tests, and evidence\n"
                "• `approve content review packet_1234abcd {JSON}` after checking facts, intent, human writing, claims, and links\n"
                "• `run website task task_1234abcd`\n"
                "• `run browser task task_1234abcd at https://example.com to INSTRUCTIONS`\n"
                "• `poll execution execution_1234abcd`\n"
                "• `review execution execution_1234abcd`, then `confirm verify execution execution_1234abcd`\n"
                "• In a client channel: `run health check website available|unavailable|unknown`\n"
                "• In a client channel: `sync search console`\n"
                "• In a client channel: `enable|disable health checks`, `website analytics`, `search console`, or `daily planning`\n"
                "• In an agency channel: `sync website metrics for 30 days` or `run due jobs`\n"
                "• `mark notification notification_1234abcd read` or `retry notification notification_1234abcd`\n"
                "• In a client channel: `mark this client active|paused|cancelled`\n"
                "Risky external work remains approval-gated and is never marked complete without execution evidence."
            ),
            changed_client_ids=(),
        )
    if action.action_type in {"save_memory", "list_memories", "update_memory", "forget_memory"}:
        from app.slack_memory_service import (
            forget_memory,
            list_memories,
            previous_user_message,
            save_memory,
            update_memory,
        )

        workspace_id = os.getenv("SLACK_WORKSPACE_ID", "").strip()
        client_id = mapped_client.id if mapped_client is not None else None
        if action.action_type == "list_memories":
            memories = list_memories(database, workspace_id=workspace_id, client_id=client_id)
            if not memories:
                return SlackOwnerActionResult(
                    text="I have no durable memories saved in this scope. Recent chat context still lasts up to 24 hours.",
                    changed_client_ids=(client_id,) if client_id else (),
                )
            rows = "\n".join(
                f"• `{memory.id}` · `{memory.category}` · {memory.content}"
                for memory in memories
            )
            return SlackOwnerActionResult(
                text=f"*Durable memories in this {'client' if client_id else 'agency'} scope*\n{rows}",
                changed_client_ids=(client_id,) if client_id else (),
            )
        try:
            if action.action_type == "save_memory":
                content = action.memory_content or previous_user_message(
                    database,
                    workspace_id=workspace_id,
                    client_id=client_id,
                    current_event_id=event_id,
                )
                memory, created = save_memory(
                    database,
                    workspace_id=workspace_id,
                    client_id=client_id,
                    slack_user_id=slack_user_id,
                    content=content or "",
                    category=action.memory_category or "general",
                )
                verb = "Saved" if created else "Updated"
            elif action.action_type == "update_memory":
                memory = update_memory(
                    database,
                    memory_id=action.memory_id or "",
                    workspace_id=workspace_id,
                    client_id=client_id,
                    slack_user_id=slack_user_id,
                    content=action.memory_content or "",
                )
                verb = "Updated"
            else:
                memory = forget_memory(
                    database,
                    memory_id=action.memory_id or "",
                    workspace_id=workspace_id,
                    client_id=client_id,
                    slack_user_id=slack_user_id,
                )
                verb = "Forgot"
        except ValueError as error:
            messages = {
                "memory_content_required": "Tell me what to remember, or say `store this in memory` immediately after the message you want saved.",
                "memory_contains_credential": "I will not store credentials or secrets in memory. Save only the non-sensitive preference or fact.",
                "memory_not_found_in_scope": "I could not find that active memory in this agency/client scope.",
            }
            return SlackOwnerActionResult(
                text=messages.get(str(error), f"Memory was not changed (`{error}`)."),
                changed_client_ids=(client_id,) if client_id else (),
            )
        record_event(
            database,
            f"slack_memory_{verb.casefold()}",
            actor=f"slack:{slack_user_id}",
            client_id=client_id,
            record_type="slack_memory",
            record_id=memory.id,
            details={"slack_event_id": event_id, "category": memory.category},
        )
        scope = mapped_client.business_name if mapped_client is not None else "agency"
        return SlackOwnerActionResult(
            text=f"{verb} durable memory `{memory.id}` in the `{scope}` scope: {memory.content}",
            changed_client_ids=(client_id,) if client_id else (),
        )
    if action.action_type == "generate_daily_plan":
        from app.daily_planning_service import generate_daily_plans, render_slack_daily_plans

        plans = generate_daily_plans(
            database,
            depth=action.mode or "simple",
            focus=action.workflow or "all",
            created_by=f"Slack {slack_user_id}",
            client=mapped_client,
        )
        for plan in plans:
            record_event(
                database,
                "slack_daily_plan_generated",
                actor=f"slack:{slack_user_id}",
                client_id=plan.client_id,
                record_type="daily_client_plan",
                record_id=plan.id,
                details={
                    "slack_event_id": event_id,
                    "depth": plan.depth,
                    "focus": plan.focus,
                    "item_count": len(plan.items),
                },
            )
        return SlackOwnerActionResult(
            text=render_slack_daily_plans(database, plans),
            changed_client_ids=tuple(plan.client_id for plan in plans),
        )
    if action.action_type == "convert_daily_plan_item":
        return _convert_daily_plan_item(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "generate_client_update":
        from app.client_update_service import generate_portfolio_update, render_slack_update

        report = generate_portfolio_update(
            database,
            mode=action.mode or "simple",
            client=mapped_client,
        )
        for client_update in report.clients:
            record_event(
                database,
                "slack_client_update_generated",
                actor=f"slack:{slack_user_id}",
                client_id=client_update.client_id,
                record_type="client_update",
                record_id=event_id,
                details={
                    "slack_event_id": event_id,
                    "mode": report.mode,
                    "gap_count": len(client_update.gaps),
                    "blocker_count": len(client_update.blockers),
                    "source_count": len(client_update.sources),
                },
            )
        return SlackOwnerActionResult(
            text=render_slack_update(report),
            changed_client_ids=tuple(item.client_id for item in report.clients),
        )
    if action.action_type == "create_client":
        return _create_client(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
        )
    if action.action_type == "propose_task":
        return _propose_task(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "decide_task":
        return _decide_task(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "change_task_status":
        return _change_task_status(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "queue_onboarding":
        return _queue_onboarding(
            database,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "request_website_generation":
        return _request_website_generation(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "submit_intake":
        return _submit_intake(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "connect_integration":
        return _connect_integration(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type in {"update_client", "archive_client", "delete_client"}:
        return _administer_client(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "intake_status":
        return _intake_status(database, mapped_client=mapped_client)
    if action.action_type in {"record_metric", "create_report"}:
        return _reporting_action(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "record_outcome":
        return _record_outcome(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type in {"approve_report", "deliver_report"}:
        return _handle_report(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "create_gbp_post":
        return _create_gbp_post(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type in {"approve_gbp_post", "publish_gbp_post"}:
        return _handle_gbp_post(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "decide_profile":
        return _decide_profile(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "correct_profile":
        return _correct_profile(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "decide_connection_candidate":
        return _decide_connection_candidate(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "prepare_website_task":
        return _prepare_website_task(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "prepare_content_task":
        return _prepare_website_task(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type in {"show_codex_packet", "handoff_codex_packet"}:
        return _codex_packet_handoff(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "record_codex_result":
        return _record_codex_result(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "record_content_review":
        return _record_content_review(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "run_website_task":
        return _run_website_task(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "run_browser_task":
        return _run_browser_task(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "poll_execution":
        return _poll_execution(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type in {"review_execution", "verify_execution"}:
        return _review_or_verify_execution(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "run_health_check":
        return _run_health_check(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "sync_website_metrics":
        return _sync_website_metrics(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "sync_search_console":
        return _sync_search_console(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type in {"mark_notification_read", "retry_notification"}:
        return _handle_notification(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "run_due_jobs":
        return _run_due_jobs(
            database,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type == "set_workflow":
        return _set_workflow(
            database,
            action,
            slack_user_id=slack_user_id,
            event_id=event_id,
            mapped_client=mapped_client,
        )
    if action.action_type != "set_client_status" or action.target_status not in CLIENT_STATUSES:
        raise ValueError("slack_owner_action_not_allowed")
    if action.all_current_clients:
        statement = select(models.Client).where(models.Client.archived_at.is_(None))
        if action.source_status:
            statement = statement.where(models.Client.status == action.source_status)
        clients = list(database.scalars(statement.order_by(models.Client.business_name.asc())))
    elif mapped_client is not None:
        clients = [mapped_client]
    else:
        raise ValueError("slack_owner_action_scope_missing")

    changed = []
    for client in clients:
        previous_status = client.status
        if previous_status == action.target_status:
            continue
        client.status = action.target_status
        record_event(
            database,
            "slack_client_status_changed",
            actor=f"slack:{slack_user_id}",
            client_id=client.id,
            record_type="client",
            record_id=client.id,
            details={
                "previous_status": previous_status,
                "new_status": action.target_status,
                "slack_event_id": event_id,
            },
        )
        changed.append(client)

    if not changed:
        source = f" in `{action.source_status}`" if action.source_status else ""
        return SlackOwnerActionResult(
            text=f"No matching current clients{source} needed a status change.",
            changed_client_ids=(),
        )
    names = "\n".join(f"• {client.business_name}" for client in changed)
    return SlackOwnerActionResult(
        text=(
            f"Done — moved *{len(changed)}* client{'s' if len(changed) != 1 else ''} "
            f"to `{action.target_status}`. This was recorded in the audit log.\n\n{names}"
        ),
        changed_client_ids=tuple(client.id for client in changed),
    )


def _create_client(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
) -> SlackOwnerActionResult:
    if action.business_name is None:
        return SlackOwnerActionResult(
            text=(
                "Which business should I create? Use `create a new client called BUSINESS NAME` "
                "and optionally add `starting YYYY-MM-DD`."
            ),
            changed_client_ids=(),
        )
    business_name = action.business_name
    existing = database.scalar(
        select(models.Client).where(func.lower(models.Client.business_name) == business_name.lower())
    )
    if existing is not None:
        return SlackOwnerActionResult(
            text=(
                f"`{existing.business_name}` already exists as `{existing.id}` with status "
                f"`{existing.status}`. I reused the existing record instead of duplicating it."
            ),
            changed_client_ids=(),
        )
    status = action.target_status if action.target_status in CLIENT_STATUSES else "onboarding"
    client = models.Client(
        business_name=business_name,
        service_start_date=action.service_start_date or date.today(),
        status=status,
    )
    database.add(client)
    database.flush()
    record_event(
        database,
        "slack_client_created",
        actor=f"slack:{slack_user_id}",
        client_id=client.id,
        record_type="client",
        record_id=client.id,
        details={
            "slack_event_id": event_id,
            "used_placeholder_name": action.business_name is None,
            "used_default_start_date": action.service_start_date is None,
            "initial_status": status,
        },
    )
    defaults = []
    if action.service_start_date is None:
        defaults.append(f"start date `{client.service_start_date.isoformat()}`")
    default_note = f" I used {', '.join(defaults)}." if defaults else ""
    channel_note = ""
    try:
        from app.slack_service import SlackIntegrationError, connect_client_channel

        channel, _ = connect_client_channel(database, client.id)
        channel_note = f" Working channel: `#{channel.channel_name}`."
    except SlackIntegrationError as error:
        channel_note = (
            f" The client is saved, but its Slack channel could not be created (`{error.code}`); "
            "fix the Slack connection and retry from Max."
        )
    return SlackOwnerActionResult(
        text=(
            f"Done — created *{business_name}* as `{client.id}` with status `{status}`."
            f"{default_note}{channel_note} The creation was recorded in the audit log."
        ),
        changed_client_ids=(client.id,),
    )


def _propose_task(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if mapped_client is None or not action.requested_outcome:
        return SlackOwnerActionResult(
            text="Which client should I attach this task to? Ask from that client's channel.",
            changed_client_ids=(),
        )
    requested_outcome = action.requested_outcome
    title = requested_outcome[:197] + "..." if len(requested_outcome) > 200 else requested_outcome
    finding = models.Finding(
        client_id=mapped_client.id,
        rule_key=f"slack_owner_request:{event_id}",
        title=title,
        explanation=f"Agency owner requested this work from Slack: {requested_outcome}",
        evidence={"slack_event_id": event_id, "slack_user_id": slack_user_id},
        source="slack_owner_request",
        severity="warning",
        confidence="confirmed",
        recommended_action=requested_outcome,
        status="open",
    )
    database.add(finding)
    database.flush()

    # Reuse the canonical proposal path so Slack cannot bypass evidence,
    # notifications, or the task lifecycle.
    from app.routes.tasks import propose_task
    from app.report_builder import expected_result_for_action, success_metric_for_action, verification_window_for_horizon

    proposal = schemas.TaskCreate(
        source_finding_id=finding.id,
        title=title,
        requested_outcome=requested_outcome,
        reason="Requested by the agency owner from the verified client Slack channel.",
        expected_result=expected_result_for_action(requested_outcome),
        success_metric=success_metric_for_action(requested_outcome),
        verification_window=verification_window_for_horizon("today"),
        estimated_effort="Needs scoping",
        risk=action.risk if action.risk in {"low", "medium", "high"} else "medium",
        required_access=[],
        dependency_ids=[],
    )
    created = propose_task(mapped_client.id, proposal, database)
    task_id = str(created["id"])
    record_event(
        database,
        "slack_task_proposed",
        actor=f"slack:{slack_user_id}",
        client_id=mapped_client.id,
        record_type="task",
        record_id=task_id,
        details={"slack_event_id": event_id, "risk": proposal.risk},
    )
    return SlackOwnerActionResult(
        text=(
            f"Created proposed task `{task_id}`: *{title}*\n"
            f"Risk: `{proposal.risk}`\n"
            "No external work has started. Approve it with `approve task "
            f"{task_id}` after reviewing the scope."
        ),
        changed_client_ids=(mapped_client.id,),
    )


def _decide_task(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    statement = select(models.Task).where(models.Task.status == "proposed")
    if action.task_id:
        statement = statement.where(models.Task.id == action.task_id)
    elif mapped_client is not None:
        statement = statement.where(models.Task.client_id == mapped_client.id)
    else:
        return SlackOwnerActionResult(
            text="Include the task ID, for example `approve task task_1234abcd`.",
            changed_client_ids=(),
        )
    tasks = list(database.scalars(statement.order_by(models.Task.proposed_at.asc()).limit(2)))
    if not tasks:
        identifier = f" `{action.task_id}`" if action.task_id else ""
        return SlackOwnerActionResult(
            text=f"I couldn't find a proposed task{identifier} in this scope.",
            changed_client_ids=(),
        )
    if len(tasks) != 1:
        task_ids = ", ".join(f"`{task.id}`" for task in tasks)
        return SlackOwnerActionResult(
            text=f"More than one task is awaiting approval. Name the task ID: {task_ids}.",
            changed_client_ids=(),
        )
    task = tasks[0]
    if mapped_client is not None and task.client_id != mapped_client.id:
        return SlackOwnerActionResult(
            text="That task belongs to a different client. Use the correct client channel.",
            changed_client_ids=(),
        )
    if action.target_status == "rejected" and not action.reason:
        return SlackOwnerActionResult(
            text=f"A rejection reason is required. Use `reject task {task.id} because REASON`.",
            changed_client_ids=(),
        )

    from app.routes.tasks import decide_task

    decision = schemas.TaskDecisionCreate(
        decision=action.target_status,
        decision_maker=f"Slack owner {slack_user_id}",
        reason=action.reason,
    )
    decide_task(database, task, decision)
    record_event(
        database,
        "slack_task_decided",
        actor=f"slack:{slack_user_id}",
        client_id=task.client_id,
        record_type="task",
        record_id=task.id,
        details={
            "slack_event_id": event_id,
            "decision": action.target_status,
            "reason": action.reason,
        },
    )
    return SlackOwnerActionResult(
        text=(
            f"Task `{task.id}` was `{action.target_status}` and the decision was recorded. "
            "Approval does not mark the work completed or verified."
        ),
        changed_client_ids=(task.client_id,),
    )


def _change_task_status(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    task, error = _scoped_task(database, action.task_id, mapped_client)
    if error is not None:
        return error
    if action.task_target_status not in {"blocked", "ready", "running", "completed", "failed", "verified"}:
        return SlackOwnerActionResult(text="That task status transition is not supported.", changed_client_ids=(task.client_id,))
    if action.task_target_status in {"blocked", "failed"} and not action.reason:
        return SlackOwnerActionResult(
            text=f"A reason is required. Use `mark task {task.id} {action.task_target_status} because REASON`.",
            changed_client_ids=(task.client_id,),
        )
    previous_status = task.status
    try:
        from app.routes.tasks import change_task_status

        changed = change_task_status(
            task.id,
            schemas.TaskStatusChange(
                target_status=action.task_target_status,
                changed_by=f"Slack owner {slack_user_id}",
                reason=action.reason,
            ),
            database,
        )
    except (HTTPException, ValidationError, ValueError) as error:
        database.rollback()
        detail = getattr(error, "detail", None) or str(error)
        return SlackOwnerActionResult(
            text=f"Task `{task.id}` was not moved to `{action.task_target_status}`: `{detail}`.",
            changed_client_ids=(task.client_id,),
        )
    record_event(
        database,
        "slack_task_status_changed",
        actor=f"slack:{slack_user_id}",
        client_id=task.client_id,
        record_type="task",
        record_id=task.id,
        details={
            "slack_event_id": event_id,
            "previous_status": previous_status,
            "new_status": action.task_target_status,
            "reason": action.reason,
        },
    )
    return SlackOwnerActionResult(
        text=f"Task `{task.id}` moved to `{changed['status']}`. No external work was started by this status change.",
        changed_client_ids=(task.client_id,),
    )


def _request_website_generation(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if mapped_client is None:
        return SlackOwnerActionResult(
            text="Request website generation from the verified client channel so Max can scope the task correctly.",
            changed_client_ids=(),
        )
    mode = action.mode if action.mode in {"new_build", "replicate", "improve"} else "replicate"
    try:
        from app.routes.codex_packets import request_website_generation

        task = request_website_generation(
            mapped_client.id,
            schemas.WebsiteGenerationTaskCreate(
                mode=mode,
                requested_outcome=f"Build the approved client website in {mode.replace('_', ' ')} mode.",
                requested_by=f"Slack owner {slack_user_id}",
            ),
            database,
        )
    except (HTTPException, ValidationError, ValueError) as error:
        database.rollback()
        detail = getattr(error, "detail", None) or str(error)
        return SlackOwnerActionResult(
            text=f"Website-generation request was not created: `{detail}`.",
            changed_client_ids=(mapped_client.id,),
        )
    record_event(
        database,
        "slack_website_generation_requested",
        actor=f"slack:{slack_user_id}",
        client_id=mapped_client.id,
        record_type="task",
        record_id=task["id"],
        details={"slack_event_id": event_id, "mode": mode},
    )
    return SlackOwnerActionResult(
        text=(
            f"Created proposed website-generation task `{task['id']}` in `{mode}` mode. "
            f"Review and approve it with `approve task {task['id']}` before any repository work."
        ),
        changed_client_ids=(mapped_client.id,),
    )


def _queue_onboarding(
    database: Session,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if mapped_client is None:
        return SlackOwnerActionResult(
            text="Which client should I onboard? Ask from that client's channel.",
            changed_client_ids=(),
        )
    from app.onboarding_automation import queue_onboarding_run

    try:
        run, reused = queue_onboarding_run(database, mapped_client.id, immediate=True)
    except ValueError as error:
        if str(error) == "intake_not_found":
            message = "This client needs an intake before automatic onboarding can start."
        else:
            message = f"Onboarding could not be queued (`{error}`)."
        return SlackOwnerActionResult(text=message, changed_client_ids=())
    record_event(
        database,
        "slack_onboarding_queued",
        actor=f"slack:{slack_user_id}",
        client_id=mapped_client.id,
        record_type="onboarding_run",
        record_id=run.id,
        details={"slack_event_id": event_id, "reused": reused},
    )
    return SlackOwnerActionResult(
        text=(
            f"Onboarding run `{run.id}` is queued at step `{run.current_step}`. "
            f"{'The existing run was resumed.' if reused else 'A new run was created.'}"
        ),
        changed_client_ids=(mapped_client.id,),
    )


def _submit_intake(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if mapped_client is None:
        return SlackOwnerActionResult(text="Submit the intake from the mapped client channel.", changed_client_ids=())
    if action.intake_parse_error:
        return SlackOwnerActionResult(text=action.intake_parse_error, changed_client_ids=(mapped_client.id,))
    try:
        intake_data = schemas.IntakeCreate.model_validate(action.intake_payload or {})
    except ValidationError as error:
        detail = getattr(error, "errors", lambda: [])()
        fields = [str(item.get("loc", ["field"])[-1]) for item in detail if isinstance(item, dict)]
        suffix = f" Missing or invalid: {', '.join(fields)}." if fields else ""
        return SlackOwnerActionResult(
            text=f"I could not validate this intake.{suffix} The source intake was not saved.",
            changed_client_ids=(mapped_client.id,),
        )
    record = models.Intake(
        client_id=mapped_client.id,
        submitted_at=datetime.utcnow(),
        **intake_data.model_dump(),
    )
    database.add(record)
    database.flush()
    from app.onboarding_automation import queue_onboarding_run

    try:
        run, reused = queue_onboarding_run(database, mapped_client.id, record.id)
    except ValueError as error:
        database.rollback()
        return SlackOwnerActionResult(
            text=f"The intake was not saved because onboarding could not be queued (`{error}`).",
            changed_client_ids=(mapped_client.id,),
        )
    record_event(
        database,
        "slack_intake_submitted",
        actor=f"slack:{slack_user_id}",
        client_id=mapped_client.id,
        record_type="intake",
        record_id=record.id,
        details={"slack_event_id": event_id, "onboarding_run_id": run.id, "reused_run": reused},
    )
    return SlackOwnerActionResult(
        text=f"Intake `{record.id}` saved immutably and onboarding run `{run.id}` is queued.",
        changed_client_ids=(mapped_client.id,),
    )


def _connect_integration(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if mapped_client is None:
        return SlackOwnerActionResult(text="Connect integrations from the mapped client channel.", changed_client_ids=())
    if action.connection_parse_error:
        return SlackOwnerActionResult(text=action.connection_parse_error, changed_client_ids=(mapped_client.id,))
    payload = action.connection_payload or {}
    route_call = {
        "website": ("app.routes.websites", "connect_website", schemas.WebsiteConnectionCreate),
        "github": ("app.routes.github_repositories", "connect_github_repository", schemas.GitHubRepositoryConnectionCreate),
        "search_console": ("app.routes.search_console", "connect_search_console", schemas.SearchConsoleConnectionCreate),
        "google_business_profile": ("app.routes.google_business_profile", "connect_profile", schemas.GoogleBusinessProfileConnectionCreate),
    }.get(action.connection_type or "")
    if route_call is None:
        return SlackOwnerActionResult(text="That integration type is not supported by Max.", changed_client_ids=())
    module_name, function_name, schema_type = route_call
    try:
        request = schema_type.model_validate(payload)
        module = __import__(module_name, fromlist=[function_name])
        saved = getattr(module, function_name)(mapped_client.id, request, database)
    except (HTTPException, ValidationError, ValueError) as error:
        database.rollback()
        detail = getattr(error, "detail", None) or str(error)
        return SlackOwnerActionResult(
            text=f"The `{action.connection_type}` connection was not saved: `{detail}`.",
            changed_client_ids=(mapped_client.id,),
        )
    record_id = str(getattr(saved, "id", event_id))
    record_event(
        database,
        "slack_integration_connected",
        actor=f"slack:{slack_user_id}",
        client_id=mapped_client.id,
        record_type=f"{action.connection_type}_connection",
        record_id=record_id,
        details={"slack_event_id": event_id},
    )
    return SlackOwnerActionResult(
        text=f"`{action.connection_type}` connection `{record_id}` saved for `{mapped_client.business_name}`. Verification remains required before external work.",
        changed_client_ids=(mapped_client.id,),
    )


def _administer_client(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if mapped_client is None:
        return SlackOwnerActionResult(
            text="Ask from the client's Slack channel so I can identify the correct client safely.",
            changed_client_ids=(),
        )
    if action.action_type in {"archive_client", "delete_client"}:
        if mapped_client.archived_at is None:
            mapped_client.archived_at = datetime.utcnow()
            mapped_client.status = "archived"
        disabled_job_ids = disable_client_jobs(database, mapped_client.id)
        connection = database.scalar(
            select(models.SlackChannelConnection).where(
                models.SlackChannelConnection.client_id == mapped_client.id
            )
        )
        record_event(
            database,
            "slack_client_deleted" if action.action_type == "delete_client" else "slack_client_archived",
            actor=f"slack:{slack_user_id}",
            client_id=mapped_client.id,
            record_type="client",
            record_id=mapped_client.id,
            details={
                "slack_event_id": event_id,
                "slack_channel_id": connection.channel_id if connection is not None else None,
                "history_preserved": True,
                "disabled_scheduled_job_ids": disabled_job_ids,
            },
        )
        verb = "removed" if action.action_type == "delete_client" else "archived"
        channel_note = " Its Slack channel was also archived." if connection is not None else ""
        return SlackOwnerActionResult(
            text=(
                f"Done — client `{mapped_client.id}` was {verb} from active clients."
                f"{channel_note} Its historical records remain preserved for auditability."
            ),
            changed_client_ids=(mapped_client.id,),
            archive_channel_id=(
                connection.channel_id
                if connection is not None
                and connection.connection_status in {"connected", "connected_public"}
                else None
            ),
        )
    if action.client_update_parse_error:
        return SlackOwnerActionResult(text=action.client_update_parse_error, changed_client_ids=(mapped_client.id,))
    try:
        update = schemas.ClientUpdate.model_validate(action.client_update_payload or {})
    except ValidationError as error:
        return SlackOwnerActionResult(text=f"Client update was not valid: `{error}`.", changed_client_ids=(mapped_client.id,))
    changes = update.model_dump(exclude_unset=True)
    if not changes:
        return SlackOwnerActionResult(text="Provide at least one editable client field in the JSON.", changed_client_ids=(mapped_client.id,))
    if "business_name" in changes:
        duplicate = database.scalar(
            select(models.Client).where(
                func.lower(models.Client.business_name) == changes["business_name"].lower(),
                models.Client.id != mapped_client.id,
            )
        )
        if duplicate is not None:
            return SlackOwnerActionResult(text=f"That name matches existing client `{duplicate.id}`; no update was saved.", changed_client_ids=(mapped_client.id,))
    before = {field: getattr(mapped_client, field) for field in changes}
    for field, value in changes.items():
        setattr(mapped_client, field, value)
    record_event(
        database,
        "slack_client_updated",
        actor=f"slack:{slack_user_id}",
        client_id=mapped_client.id,
        record_type="client",
        record_id=mapped_client.id,
        details={"slack_event_id": event_id, "before": {key: str(value) for key, value in before.items()}, "changes": {key: str(value) for key, value in changes.items()}},
    )
    return SlackOwnerActionResult(text=f"Client `{mapped_client.id}` updated: {', '.join(sorted(changes))}.", changed_client_ids=(mapped_client.id,))


def _intake_status(
    database: Session,
    *,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if mapped_client is None:
        return SlackOwnerActionResult(
            text="Ask from the mapped client channel so I can show that client's intake.",
            changed_client_ids=(),
        )
    intake = database.scalar(
        select(models.Intake)
        .where(models.Intake.client_id == mapped_client.id)
        .order_by(models.Intake.submitted_at.desc())
        .limit(1)
    )
    if intake is None:
        return SlackOwnerActionResult(
            text=(
                f"`{mapped_client.business_name}` has no intake yet. Submit the immutable intake "
                "through the owner form/API, then ask me to start onboarding."
            ),
            changed_client_ids=(mapped_client.id,),
        )
    proposal = database.scalar(
        select(models.InterpretationProposal)
        .where(models.InterpretationProposal.intake_id == intake.id)
        .order_by(models.InterpretationProposal.processed_at.desc())
        .limit(1)
    )
    missing = list(proposal.missing_information) if proposal is not None else []
    conflicts = list(proposal.conflicting_information) if proposal is not None else []
    run = database.scalar(
        select(models.OnboardingAutomationRun)
        .where(models.OnboardingAutomationRun.client_id == mapped_client.id)
        .order_by(models.OnboardingAutomationRun.created_at.desc())
        .limit(1)
    )
    lines = [
        f"*Intake status · {mapped_client.business_name}*",
        f"Intake `{intake.id}`: `{intake.status}` (submitted {intake.submitted_at.date().isoformat()})",
        f"Client lifecycle: `{mapped_client.status}`",
        f"Onboarding run: `{run.status}` at `{run.current_step}`" if run is not None else "Onboarding run: not queued",
        f"Missing information: {', '.join(missing) if missing else 'none recorded'}",
        f"Conflicts to resolve: {', '.join(conflicts) if conflicts else 'none recorded'}",
    ]
    return SlackOwnerActionResult(text="\n".join(lines), changed_client_ids=(mapped_client.id,))


def _reporting_action(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if mapped_client is None:
        return SlackOwnerActionResult(text="Run reporting actions from the mapped client channel.", changed_client_ids=())
    from app.routes.metrics import create_metric
    from app.routes.reports import create_report
    if action.action_type == "record_metric":
        if action.metric_parse_error:
            return SlackOwnerActionResult(text=action.metric_parse_error, changed_client_ids=(mapped_client.id,))
        try:
            metric = schemas.MetricCreate.model_validate(action.metric_payload or {})
            saved = create_metric(mapped_client.id, metric, database)
        except (HTTPException, ValidationError, ValueError) as error:
            detail = getattr(error, "detail", None) or str(error)
            database.rollback()
            return SlackOwnerActionResult(text=f"Metric was not saved: `{detail}`.", changed_client_ids=(mapped_client.id,))
        record_event(
            database,
            "slack_metric_recorded",
            actor=f"slack:{slack_user_id}",
            client_id=mapped_client.id,
            record_type="metric_snapshot",
            record_id=saved.id,
            details={"slack_event_id": event_id, "source_type": saved.source_type},
        )
        return SlackOwnerActionResult(
            text=f"Metric `{saved.metric_name}` for `{saved.measurement_period}` saved as `{saved.source_type}` (`{saved.id}`).",
            changed_client_ids=(mapped_client.id,),
        )
    if action.report_parse_error:
        return SlackOwnerActionResult(text=action.report_parse_error, changed_client_ids=(mapped_client.id,))
    payload = dict(action.report_payload or {})
    payload.setdefault("generated_by", f"Slack owner {slack_user_id}")
    try:
        report_request = schemas.ReportCreate.model_validate(payload)
        saved_report = create_report(mapped_client.id, report_request, database)
    except (HTTPException, ValidationError, ValueError) as error:
        detail = getattr(error, "detail", None) or str(error)
        database.rollback()
        return SlackOwnerActionResult(text=f"Report was not created: `{detail}`.", changed_client_ids=(mapped_client.id,))
    record_event(
        database,
        "slack_report_created",
        actor=f"slack:{slack_user_id}",
        client_id=mapped_client.id,
        record_type="report",
        record_id=saved_report.id,
        details={"slack_event_id": event_id, "report_type": saved_report.report_type},
    )
    return SlackOwnerActionResult(
        text=f"Report `{saved_report.id}` created as `{saved_report.status}`. Review it, then use `approve report {saved_report.id}`.",
        changed_client_ids=(mapped_client.id,),
    )


def _record_outcome(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    """Record a post-work result without allowing Slack to bypass task scope."""
    if mapped_client is None:
        return SlackOwnerActionResult(
            text="Record outcome measurements from the mapped client channel.",
            changed_client_ids=(),
        )
    if action.outcome_parse_error:
        return SlackOwnerActionResult(
            text=action.outcome_parse_error,
            changed_client_ids=(mapped_client.id,),
        )
    from app.routes.tasks import record_outcome_measurement

    payload = dict(action.outcome_payload or {})
    payload.setdefault("recorded_by", f"Slack owner {slack_user_id}")
    payload.setdefault("operation_key", f"slack-outcome:{event_id}")
    try:
        measurement = schemas.OutcomeMeasurementCreate.model_validate(payload)
        saved = record_outcome_measurement(action.task_id or "", measurement, database)
    except (HTTPException, ValidationError, ValueError) as error:
        detail = getattr(error, "detail", None) or str(error)
        database.rollback()
        return SlackOwnerActionResult(
            text=f"Outcome was not saved: `{detail}`.",
            changed_client_ids=(mapped_client.id,),
        )
    record_event(
        database,
        "slack_outcome_recorded",
        actor=f"slack:{slack_user_id}",
        client_id=mapped_client.id,
        record_type="outcome_measurement",
        record_id=saved["id"],
        details={
            "slack_event_id": event_id,
            "task_id": action.task_id,
            "assessment": saved["assessment"],
            "source_type": saved["source_type"],
            "reused_existing": saved.get("reused_existing", False),
        },
    )
    return SlackOwnerActionResult(
        text=(
            f"Outcome for task `{action.task_id}` recorded as `{saved['assessment']}` "
            f"for `{saved['metric_name']}` from `{saved['source_reference']}`."
        ),
        changed_client_ids=(mapped_client.id,),
    )


def _handle_report(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    statement = select(models.Report)
    if action.report_id:
        statement = statement.where(models.Report.id == action.report_id)
    elif mapped_client is not None:
        target_status = "draft" if action.action_type == "approve_report" else "approved"
        statement = statement.where(
            models.Report.client_id == mapped_client.id,
            models.Report.status == target_status,
        )
    else:
        return SlackOwnerActionResult(
            text="Include the report ID, for example `approve report report_1234abcd`.",
            changed_client_ids=(),
        )
    reports = list(database.scalars(statement.order_by(models.Report.created_at.desc()).limit(2)))
    if not reports:
        identifier = f" `{action.report_id}`" if action.report_id else ""
        return SlackOwnerActionResult(
            text=f"I couldn't find a matching report{identifier} in this scope.",
            changed_client_ids=(),
        )
    if len(reports) != 1:
        report_ids = ", ".join(f"`{report.id}`" for report in reports)
        return SlackOwnerActionResult(
            text=f"More than one report matches. Name the report ID: {report_ids}.",
            changed_client_ids=(),
        )
    report = reports[0]
    if mapped_client is not None and report.client_id != mapped_client.id:
        return SlackOwnerActionResult(
            text="That report belongs to a different client. Use the correct client channel.",
            changed_client_ids=(),
        )

    if action.action_type == "approve_report":
        if report.status == "approved":
            return SlackOwnerActionResult(
                text=f"Report `{report.id}` is already approved.",
                changed_client_ids=(),
            )
        from app.routes.reports import approve_report

        approve_report(
            report.id,
            schemas.ReportApprovalCreate(approved_by=f"Slack owner {slack_user_id}"),
            database,
        )
        record_event(
            database,
            "slack_report_approved",
            actor=f"slack:{slack_user_id}",
            client_id=report.client_id,
            record_type="report",
            record_id=report.id,
            details={"slack_event_id": event_id},
        )
        return SlackOwnerActionResult(
            text=(
                f"Approved report `{report.id}`: *{report.title}*. "
                f"Send it with `send report {report.id}`."
            ),
            changed_client_ids=(report.client_id,),
        )

    if report.report_type != "client":
        return SlackOwnerActionResult(
            text="Only client reports can be delivered to a client Slack channel.",
            changed_client_ids=(),
        )
    if report.status != "approved":
        return SlackOwnerActionResult(
            text=f"Report `{report.id}` must be approved before delivery.",
            changed_client_ids=(),
        )
    from fastapi import HTTPException
    from app.routes.reports import deliver_report_record

    try:
        delivery = deliver_report_record(database, report)
    except HTTPException as error:
        return SlackOwnerActionResult(
            text=f"Report delivery did not complete (`{error.detail}`).",
            changed_client_ids=(),
        )
    record_event(
        database,
        "slack_report_delivery_requested",
        actor=f"slack:{slack_user_id}",
        client_id=report.client_id,
        record_type="report_delivery",
        record_id=delivery.id,
        details={"slack_event_id": event_id, "status": delivery.status},
    )
    return SlackOwnerActionResult(
        text=f"Report `{report.id}` delivery status: `{delivery.status}` (attempt {delivery.attempt_count}).",
        changed_client_ids=(report.client_id,),
    )


def _create_gbp_post(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if mapped_client is None:
        return SlackOwnerActionResult(
            text="Create GBP posts from the verified client channel so Max can scope the post correctly.",
            changed_client_ids=(),
        )
    if action.gbp_post_parse_error:
        return SlackOwnerActionResult(
            text=action.gbp_post_parse_error,
            changed_client_ids=(mapped_client.id,),
        )
    payload = dict(action.gbp_post_payload or {})
    payload.setdefault("operation_key", f"slack-gbp-{event_id[-24:]}")
    try:
        request = schemas.GoogleBusinessProfilePostCreate(**payload)
        from app.routes.google_business_profile import create_post

        post = create_post(mapped_client.id, request, database)
    except (HTTPException, ValidationError, ValueError) as error:
        database.rollback()
        detail = getattr(error, "detail", None) or str(error)
        return SlackOwnerActionResult(
            text=f"GBP post draft was not saved: `{detail}`.",
            changed_client_ids=(mapped_client.id,),
        )
    record_event(
        database,
        "slack_gbp_post_created",
        actor=f"slack:{slack_user_id}",
        client_id=mapped_client.id,
        record_type="google_business_profile_post",
        record_id=post.id,
        details={"slack_event_id": event_id, "operation_key": post.operation_key},
    )
    return SlackOwnerActionResult(
        text=(
            f"Created GBP post draft `{post.id}`. It is not published. "
            f"Review and approve it with `approve GBP post {post.id}`, then publish explicitly."
        ),
        changed_client_ids=(mapped_client.id,),
    )


def _handle_gbp_post(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if not action.gbp_post_id:
        return SlackOwnerActionResult(text="Provide the GBP post ID.", changed_client_ids=())
    post = database.get(models.GoogleBusinessProfilePost, action.gbp_post_id)
    if post is None:
        return SlackOwnerActionResult(text=f"GBP post `{action.gbp_post_id}` was not found.", changed_client_ids=())
    if mapped_client is None or post.client_id != mapped_client.id:
        return SlackOwnerActionResult(
            text="That GBP post is not attached to the client represented by this channel.",
            changed_client_ids=(),
        )
    if action.action_type == "approve_gbp_post":
        if post.status != "draft":
            return SlackOwnerActionResult(
                text=f"GBP post `{post.id}` is `{post.status}`; only drafts can be approved.",
                changed_client_ids=(post.client_id,),
            )
        post.status = "approved"
        post.approved_by = f"slack:{slack_user_id}"
        post.approved_at = datetime.utcnow()
        record_event(
            database,
            "slack_gbp_post_approved",
            actor=f"slack:{slack_user_id}",
            client_id=post.client_id,
            record_type="google_business_profile_post",
            record_id=post.id,
            details={"slack_event_id": event_id},
        )
        return SlackOwnerActionResult(
            text=f"GBP post `{post.id}` is approved. Publishing is still a separate explicit command.",
            changed_client_ids=(post.client_id,),
        )
    if post.status == "published":
        return SlackOwnerActionResult(text=f"GBP post `{post.id}` is already published.", changed_client_ids=(post.client_id,))
    if post.status != "approved":
        return SlackOwnerActionResult(
            text=f"GBP post `{post.id}` is `{post.status}`. Approve it first; publishing never bypasses approval.",
            changed_client_ids=(post.client_id,),
        )
    from app.subscription_service import require_fulfillment_entitlement

    require_fulfillment_entitlement(database, post.client_id)
    from app.google_business_profile_service import GoogleBusinessProfileAdapter, GoogleBusinessProfileIntegrationError

    connection = database.get(models.GoogleBusinessProfileConnection, post.connection_id)
    if connection is None or connection.client_id != post.client_id:
        return SlackOwnerActionResult(text="The GBP connection does not match this client; publishing stopped.", changed_client_ids=())
    try:
        result = GoogleBusinessProfileAdapter().publish_post(
            connection.location_id, post.summary, post.call_to_action_url
        )
    except GoogleBusinessProfileIntegrationError as error:
        post.status = "failed"
        post.error_code = error.code
        record_event(
            database,
            "slack_gbp_post_publish_failed",
            actor=f"slack:{slack_user_id}",
            client_id=post.client_id,
            record_type="google_business_profile_post",
            record_id=post.id,
            details={"slack_event_id": event_id, "error": error.code},
        )
        return SlackOwnerActionResult(
            text=f"GBP post `{post.id}` failed to publish (`{error.code}`). It was not reported as published.",
            changed_client_ids=(post.client_id,),
        )
    post.status = "published"
    post.external_post_id = result.post_id
    post.published_at = datetime.utcnow()
    record_event(
        database,
        "slack_gbp_post_published",
        actor=f"slack:{slack_user_id}",
        client_id=post.client_id,
        record_type="google_business_profile_post",
        record_id=post.id,
        details={"slack_event_id": event_id, "external_post_id": result.post_id},
    )
    return SlackOwnerActionResult(
        text=f"GBP post `{post.id}` published with live reference `{result.post_id}`.",
        changed_client_ids=(post.client_id,),
    )


def _correct_profile(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    version = database.get(models.ProfileVersion, action.profile_version_id)
    if version is None:
        return SlackOwnerActionResult(text=f"Profile version `{action.profile_version_id}` was not found.", changed_client_ids=())
    if mapped_client is None or version.client_id != mapped_client.id:
        return SlackOwnerActionResult(text="That profile belongs to a different client. Use the correct client channel.", changed_client_ids=())
    if action.profile_correction_parse_error:
        return SlackOwnerActionResult(text=action.profile_correction_parse_error, changed_client_ids=(version.client_id,))
    try:
        correction = schemas.ProfileCorrection(
            decision_maker=f"Slack owner {slack_user_id}",
            profile_data=action.profile_correction_payload or {},
        )
        from app.routes.interpretations import correct_profile_version

        corrected = correct_profile_version(version.id, correction, database)
    except (HTTPException, ValidationError, ValueError) as error:
        detail = getattr(error, "detail", None) or str(error)
        database.rollback()
        return SlackOwnerActionResult(text=f"Profile correction was not saved: `{detail}`.", changed_client_ids=(version.client_id,))
    record_event(
        database,
        "slack_profile_corrected",
        actor=f"slack:{slack_user_id}",
        client_id=version.client_id,
        record_type="profile_version",
        record_id=corrected.id,
        details={"slack_event_id": event_id, "previous_version_id": version.id},
    )
    return SlackOwnerActionResult(
        text=f"Corrected profile version `{version.id}` into new pending version `{corrected.id}`. Review and approve it when ready.",
        changed_client_ids=(version.client_id,),
    )


def _decide_profile(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    statement = select(models.ProfileVersion).where(models.ProfileVersion.status == "pending")
    if action.profile_version_id:
        statement = statement.where(models.ProfileVersion.id == action.profile_version_id)
    elif mapped_client is not None:
        statement = statement.where(models.ProfileVersion.client_id == mapped_client.id)
    else:
        return SlackOwnerActionResult(
            text="Include the profile version ID, for example `approve profile profile_version_1234abcd`.",
            changed_client_ids=(),
        )
    versions = list(
        database.scalars(statement.order_by(models.ProfileVersion.version_number.desc()).limit(2))
    )
    if not versions:
        identifier = f" `{action.profile_version_id}`" if action.profile_version_id else ""
        return SlackOwnerActionResult(
            text=f"I couldn't find a pending profile{identifier} in this scope.",
            changed_client_ids=(),
        )
    if len(versions) != 1:
        version_ids = ", ".join(f"`{version.id}`" for version in versions)
        return SlackOwnerActionResult(
            text=f"More than one profile is pending. Name the version ID: {version_ids}.",
            changed_client_ids=(),
        )
    version = versions[0]
    if mapped_client is not None and version.client_id != mapped_client.id:
        return SlackOwnerActionResult(
            text="That profile belongs to a different client. Use the correct client channel.",
            changed_client_ids=(),
        )
    if action.target_status == "reject" and not action.reason:
        return SlackOwnerActionResult(
            text=f"A rejection reason is required. Use `reject profile {version.id} because REASON`.",
            changed_client_ids=(),
        )

    from fastapi import HTTPException
    from app.routes.interpretations import decide_profile_version

    try:
        decided = decide_profile_version(
            version.id,
            schemas.ProfileDecision(
                decision=action.target_status,
                decision_maker=f"Slack owner {slack_user_id}",
                reason=action.reason,
            ),
            database,
        )
    except HTTPException as error:
        return SlackOwnerActionResult(
            text=f"Profile decision was not applied: {error.detail}.",
            changed_client_ids=(),
        )
    record_event(
        database,
        "slack_profile_decided",
        actor=f"slack:{slack_user_id}",
        client_id=version.client_id,
        record_type="profile_version",
        record_id=version.id,
        details={
            "slack_event_id": event_id,
            "decision": action.target_status,
            "reason": action.reason,
        },
    )
    return SlackOwnerActionResult(
        text=f"Profile `{version.id}` was `{decided.status}` and the decision was recorded.",
        changed_client_ids=(version.client_id,),
    )


def _decide_connection_candidate(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    candidate = (
        database.get(models.ConnectionCandidate, action.connection_candidate_id)
        if action.connection_candidate_id
        else None
    )
    if candidate is None or candidate.status != "pending":
        return SlackOwnerActionResult(
            text=f"I couldn't find pending connection candidate `{action.connection_candidate_id}`.",
            changed_client_ids=(),
        )
    if mapped_client is not None and candidate.client_id != mapped_client.id:
        return SlackOwnerActionResult(
            text="That connection candidate belongs to a different client. Use the correct client channel.",
            changed_client_ids=(),
        )
    if action.target_status == "reject" and not action.reason:
        return SlackOwnerActionResult(
            text=(
                f"A rejection reason is required. Use `reject connection candidate {candidate.id} "
                "because REASON`."
            ),
            changed_client_ids=(),
        )

    from fastapi import HTTPException
    from app.routes.onboarding_automation import decide_connection_candidate

    try:
        decided = decide_connection_candidate(
            candidate.id,
            schemas.ConnectionCandidateDecision(
                decision=action.target_status,
                decided_by=f"Slack owner {slack_user_id}",
                reason=action.reason,
            ),
            database,
        )
    except HTTPException as error:
        return SlackOwnerActionResult(
            text=f"Connection decision was not applied: {error.detail}.",
            changed_client_ids=(),
        )
    record_event(
        database,
        "slack_connection_candidate_decided",
        actor=f"slack:{slack_user_id}",
        client_id=candidate.client_id,
        record_type="connection_candidate",
        record_id=candidate.id,
        details={
            "slack_event_id": event_id,
            "decision": action.target_status,
            "reason": action.reason,
        },
    )
    return SlackOwnerActionResult(
        text=(
            f"Connection candidate `{candidate.id}` ({candidate.provider}: {candidate.display_name}) "
            f"was `{decided.status}`."
        ),
        changed_client_ids=(candidate.client_id,),
    )


def _scoped_task(
    database: Session,
    task_id: str | None,
    mapped_client: models.Client | None,
) -> tuple[models.Task | None, SlackOwnerActionResult | None]:
    task = database.get(models.Task, task_id) if task_id else None
    if task is None:
        return None, SlackOwnerActionResult(
            text=f"I couldn't find task `{task_id}`.",
            changed_client_ids=(),
        )
    if mapped_client is not None and task.client_id != mapped_client.id:
        return None, SlackOwnerActionResult(
            text="That task belongs to a different client. Use the correct client channel.",
            changed_client_ids=(),
        )
    return task, None


def _scoped_execution(
    database: Session,
    execution_id: str | None,
    mapped_client: models.Client | None,
) -> tuple[models.FulfillmentExecution | None, SlackOwnerActionResult | None]:
    execution = database.get(models.FulfillmentExecution, execution_id) if execution_id else None
    if execution is None:
        return None, SlackOwnerActionResult(
            text=f"I couldn't find execution `{execution_id}`.",
            changed_client_ids=(),
        )
    if mapped_client is not None and execution.client_id != mapped_client.id:
        return None, SlackOwnerActionResult(
            text="That execution belongs to a different client. Use the correct client channel.",
            changed_client_ids=(),
        )
    return execution, None


def _prepare_website_task(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    task, error = _scoped_task(database, action.task_id, mapped_client)
    if error is not None:
        return error
    repository = database.scalar(
        select(models.GitHubRepositoryConnection).where(
            models.GitHubRepositoryConnection.client_id == task.client_id
        )
    )
    website = database.scalar(
        select(models.WebsiteConnection).where(models.WebsiteConnection.client_id == task.client_id)
    )
    if repository is None or website is None:
        missing = []
        if repository is None:
            missing.append("verified GitHub repository")
        if website is None:
            missing.append("verified website/Vercel project")
        return SlackOwnerActionResult(
            text=f"I can't prepare this task until Max has a {' and '.join(missing)} for the client.",
            changed_client_ids=(),
        )

    from app.codex_packet_service import WorkPacketError, create_work_packet

    title = task.title.casefold()
    seo_work_type = action.seo_work_type or (
        "technical_seo" if "technical" in title or "sitemap" in title else "website_build"
    )
    if seo_work_type not in {"website_build", "technical_seo", "local_page", "blog"}:
        return SlackOwnerActionResult(
            text="This content task type is not supported; use `local_page` or `blog`.",
            changed_client_ids=(),
        )
    request = schemas.CodexWorkPacketCreate(
        operation_key=f"slack-packet-{event_id[-24:]}",
        created_by=f"Slack owner {slack_user_id}",
        mode=action.mode if action.mode in {"new_build", "replicate", "improve", "repair"} else "improve",
        seo_work_type=seo_work_type,
        repository_owner=repository.owner,
        repository_name=repository.repository_name,
        repository_url=repository.repository_url,
        branch=repository.default_branch,
        vercel_project_id=website.external_project_id,
        domain=website.production_url,
        allowed_paths=[
            "app/**",
            "src/**",
            "pages/**",
            "components/**",
            "public/**",
            "styles/**",
            "package.json",
            "next.config.*",
            "vite.config.*",
        ],
        publish_allowed=False,
        task_specific_instructions="Prepared from a signed owner request in the verified Slack workspace.",
    )
    try:
        packet, reused = create_work_packet(database, task.id, request)
    except WorkPacketError as packet_error:
        return SlackOwnerActionResult(
            text=f"Website task preparation stopped: {packet_error.detail}.",
            changed_client_ids=(),
        )
    record_event(
        database,
        "slack_website_task_prepared",
        actor=f"slack:{slack_user_id}",
        client_id=task.client_id,
        record_type="codex_work_packet",
        record_id=packet.id,
        details={"slack_event_id": event_id, "task_id": task.id, "reused": reused},
    )
    next_step = (
        f"Use `handoff codex packet {packet.id}`; content packets require the structured Codex/content review path."
        if seo_work_type in {"local_page", "blog"}
        else f"Use `handoff codex packet {packet.id}` for the low-cost manual Codex path, or `run website task {task.id} using packet {packet.id}` for Max API generation."
    )
    return SlackOwnerActionResult(
        text=(
            f"Prepared packet `{packet.id}` for task `{task.id}` in `{packet.mode}` mode. "
            f"No files changed yet. {next_step}"
        ),
        changed_client_ids=(task.client_id,),
    )


def _convert_daily_plan_item(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if mapped_client is None:
        return SlackOwnerActionResult(text="Convert a daily-plan recommendation from its mapped client channel.", changed_client_ids=())
    from app.daily_planning_service import DailyPlanTaskError, convert_plan_item_to_task

    plan = database.scalar(
        select(models.DailyClientPlan).where(
            models.DailyClientPlan.client_id == mapped_client.id,
            models.DailyClientPlan.plan_date == date.today(),
        )
    )
    if plan is None:
        return SlackOwnerActionResult(text="There is no daily plan for this client today. Generate one first.", changed_client_ids=())
    try:
        task, reused = convert_plan_item_to_task(
            database,
            plan,
            action.daily_plan_item_index if action.daily_plan_item_index is not None else -1,
            created_by=f"Slack {slack_user_id}",
        )
    except DailyPlanTaskError as error:
        return SlackOwnerActionResult(text=f"I couldn't convert that daily-plan item: {error}.", changed_client_ids=())
    record_event(
        database,
        "slack_daily_plan_item_converted",
        actor=f"slack:{slack_user_id}",
        client_id=mapped_client.id,
        record_type="task",
        record_id=task.id,
        details={"slack_event_id": event_id, "plan_id": plan.id, "item_index": action.daily_plan_item_index, "reused": reused},
    )
    return SlackOwnerActionResult(
        text=(
            f"Task `{task.id}` was already linked to daily-plan item `{(action.daily_plan_item_index or 0) + 1}`."
            if reused
            else f"Created approval-required task `{task.id}` from daily-plan item `{(action.daily_plan_item_index or 0) + 1}`. Review and approve it here; no external work has started."
        ),
        changed_client_ids=(mapped_client.id,),
    )


def _scoped_packet(
    database: Session,
    packet_id: str | None,
    mapped_client: models.Client | None,
) -> tuple[models.CodexWorkPacket | None, SlackOwnerActionResult | None]:
    packet = database.get(models.CodexWorkPacket, packet_id) if packet_id else None
    if packet is None:
        return None, SlackOwnerActionResult(text=f"I couldn't find Codex packet `{packet_id}`.", changed_client_ids=())
    if mapped_client is not None and packet.client_id != mapped_client.id:
        return None, SlackOwnerActionResult(
            text="That Codex packet belongs to a different client. Use the correct client channel.",
            changed_client_ids=(),
        )
    return packet, None


def _codex_packet_handoff(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    packet, error = _scoped_packet(database, action.packet_id, mapped_client)
    if error is not None:
        return error
    from app.codex_packet_service import WorkPacketError, mark_packet_handed_off, packet_quality, render_handoff_text
    quality = packet_quality(packet)

    if action.action_type == "handoff_codex_packet":
        try:
            mark_packet_handed_off(database, packet, handed_off_by=f"Slack {slack_user_id}")
        except WorkPacketError as packet_error:
            return SlackOwnerActionResult(text=f"Codex handoff stopped: {packet_error.detail}.", changed_client_ids=())
        record_event(
            database,
            "codex_packet_handed_off",
            actor=f"slack:{slack_user_id}",
            client_id=packet.client_id,
            record_type="codex_work_packet",
            record_id=packet.id,
            details={"slack_event_id": event_id, "task_id": packet.task_id},
        )
        prefix = f"Packet `{packet.id}` is now handed off and task `{packet.task_id}` is running. Copy everything below into Codex.\n\n"
    else:
        prefix = f"Preview of packet `{packet.id}`. This has not marked the task as running.\n\n"
    return SlackOwnerActionResult(
        text=(
            prefix
            + f"Packet quality: `{quality['status']}` ({quality['summary']['passed']} passed, {quality['summary']['blocked']} blocked).\n"
            + render_handoff_text(packet)
        )[:35_000],
        changed_client_ids=(packet.client_id,),
    )


def _record_codex_result(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    packet, error = _scoped_packet(database, action.packet_id, mapped_client)
    if error is not None:
        return error
    if action.codex_result_parse_error:
        return SlackOwnerActionResult(text=action.codex_result_parse_error, changed_client_ids=())
    try:
        request = schemas.CodexHandoffResultCreate.model_validate(action.codex_result_payload or {})
    except ValidationError as validation_error:
        fields = ", ".join(".".join(str(part) for part in item["loc"]) for item in validation_error.errors()[:8])
        return SlackOwnerActionResult(
            text=f"The Codex result is missing or has invalid fields: `{fields}`. No result was saved.",
            changed_client_ids=(),
        )
    from app.codex_packet_service import WorkPacketError, record_codex_result

    try:
        execution, reused = record_codex_result(database, packet, request)
    except WorkPacketError as result_error:
        return SlackOwnerActionResult(text=f"Codex result stopped: {result_error.detail}.", changed_client_ids=())
    record_event(
        database,
        "codex_handoff_result_recorded",
        actor=f"slack:{slack_user_id}",
        client_id=packet.client_id,
        record_type="execution",
        record_id=execution.id,
        details={
            "slack_event_id": event_id,
            "packet_id": packet.id,
            "task_id": packet.task_id,
            "outcome": execution.status,
            "reused": reused,
        },
    )
    if execution.status == "completed":
        next_step = f"Review evidence with `review execution {execution.id}`, then verify it separately."
    else:
        next_step = "Resolve the returned blocker/failure before retrying the task."
    return SlackOwnerActionResult(
        text=f"Recorded Codex result `{execution.status}` as execution `{execution.id}` for packet `{packet.id}`. {next_step}",
        changed_client_ids=(packet.client_id,),
    )


def _record_content_review(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    packet, error = _scoped_packet(database, action.packet_id, mapped_client)
    if error is not None:
        return error
    if action.content_review_parse_error:
        return SlackOwnerActionResult(text=action.content_review_parse_error, changed_client_ids=())
    from app.routes.codex_packets import record_content_review

    payload = dict(action.content_review_payload or {})
    payload.setdefault("reviewer", f"Slack owner {slack_user_id}")
    payload.setdefault("status", "approved")
    payload.setdefault("notes", "Reviewed in the mapped client Slack channel.")
    try:
        review = schemas.ContentReviewCreate.model_validate(payload)
        saved = record_content_review(packet.id, review, database)
    except (HTTPException, ValidationError, ValueError) as caught:
        detail = getattr(caught, "detail", None) or str(caught)
        database.rollback()
        return SlackOwnerActionResult(
            text=f"Content review was not saved: `{detail}`.",
            changed_client_ids=(packet.client_id,),
        )
    record_event(
        database,
        "slack_content_review_recorded",
        actor=f"slack:{slack_user_id}",
        client_id=packet.client_id,
        record_type="content_review",
        record_id=saved["id"],
        details={"slack_event_id": event_id, "packet_id": packet.id, "status": saved["status"]},
    )
    return SlackOwnerActionResult(
        text=f"Content review for packet `{packet.id}` recorded as `{saved['status']}`. Independent verification may proceed only when it is approved.",
        changed_client_ids=(packet.client_id,),
    )


def _run_website_task(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    task, error = _scoped_task(database, action.task_id, mapped_client)
    if error is not None:
        return error
    if action.packet_id:
        packet = database.get(models.CodexWorkPacket, action.packet_id)
    else:
        packet = database.scalar(
            select(models.CodexWorkPacket)
            .where(models.CodexWorkPacket.task_id == task.id)
            .order_by(models.CodexWorkPacket.created_at.desc())
            .limit(1)
        )
    if packet is None or packet.task_id != task.id or packet.client_id != task.client_id:
        return SlackOwnerActionResult(
            text=f"No matching work packet exists. Use `prepare website task {task.id} as improve` first.",
            changed_client_ids=(),
        )

    packet_work_type = str((packet.packet_data or {}).get("local_seo_work_type", "website_build"))
    if packet_work_type in {"local_page", "blog"}:
        return SlackOwnerActionResult(
            text=(
                f"Packet `{packet.id}` is a `{packet_work_type}` content packet. "
                f"Use `handoff codex packet {packet.id}` so the content brief, human-writing review, and acceptance checks remain attached."
            ),
            changed_client_ids=(task.client_id,),
        )

    from fastapi import HTTPException
    from app.routes.website_generation import generate_and_execute_website

    try:
        result = generate_and_execute_website(
            task.id,
            schemas.WebsiteGenerationCreate(
                operation_key=f"slack-website-{event_id[-24:]}",
                packet_id=packet.id,
                commit_message=f"Complete approved Max task {task.id}",
                model_role="quality",
            ),
            database,
        )
    except HTTPException as execution_error:
        return SlackOwnerActionResult(
            text=f"Website execution stopped (`{execution_error.detail}`). No completion was claimed.",
            changed_client_ids=(),
        )
    execution_id = str(result["id"])
    record_event(
        database,
        "slack_website_execution_requested",
        actor=f"slack:{slack_user_id}",
        client_id=task.client_id,
        record_type="execution",
        record_id=execution_id,
        details={"slack_event_id": event_id, "task_id": task.id, "packet_id": packet.id},
    )
    return SlackOwnerActionResult(
        text=(
            f"Website execution `{execution_id}` finished with status `{result['status']}`. "
            f"Review it with `review execution {execution_id}`; completion is not verification."
        ),
        changed_client_ids=(task.client_id,),
    )


def _run_browser_task(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    task, error = _scoped_task(database, action.task_id, mapped_client)
    if error is not None:
        return error
    from fastapi import HTTPException
    from app.routes.browser_execution import submit_browser_execution
    from app.routes.tasks import approve_browser_control

    try:
        # The owner's explicit Slack command is the browser-control approval;
        # persist its exact scope before submitting to the isolated worker.
        approve_browser_control(
            database,
            task,
            schemas.BrowserControlApprovalCreate(
                approved_by=f"slack:{slack_user_id}",
                reason=f"Owner requested browser task at {action.target_url}: {action.instructions}",
            ),
        )
        result = submit_browser_execution(
            task.id,
            schemas.BrowserExecutionCreate(
                operation_key=f"slack-browser-{event_id[-24:]}",
                target_url=action.target_url,
                instructions=action.instructions,
                estimated_cost=0.0,
            ),
            database,
        )
    except HTTPException as execution_error:
        return SlackOwnerActionResult(
            text=f"Browser execution stopped (`{execution_error.detail}`). No completion was claimed.",
            changed_client_ids=(),
        )
    execution_id = str(result["id"])
    record_event(
        database,
        "slack_browser_execution_requested",
        actor=f"slack:{slack_user_id}",
        client_id=task.client_id,
        record_type="execution",
        record_id=execution_id,
        details={"slack_event_id": event_id, "task_id": task.id, "target_url": action.target_url},
    )
    return SlackOwnerActionResult(
        text=(
            f"Browser execution `{execution_id}` is `{result['status']}`. "
            f"Check it with `poll execution {execution_id}`."
        ),
        changed_client_ids=(task.client_id,),
    )


def _poll_execution(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    execution, error = _scoped_execution(database, action.execution_id, mapped_client)
    if error is not None:
        return error
    if execution.evidence.get("executor") != "browser_worker":
        return SlackOwnerActionResult(
            text=f"Execution `{execution.id}` is not a browser-worker execution and does not need polling.",
            changed_client_ids=(),
        )
    from fastapi import HTTPException
    from app.routes.browser_execution import poll_browser_execution

    try:
        result = poll_browser_execution(execution.id, database)
    except HTTPException as poll_error:
        return SlackOwnerActionResult(
            text=f"Execution polling failed (`{poll_error.detail}`).",
            changed_client_ids=(),
        )
    record_event(
        database,
        "slack_execution_polled",
        actor=f"slack:{slack_user_id}",
        client_id=execution.client_id,
        record_type="execution",
        record_id=execution.id,
        details={"slack_event_id": event_id, "status": result["status"]},
    )
    next_step = (
        f" Review it with `review execution {execution.id}`."
        if result["status"] == "completed"
        else ""
    )
    return SlackOwnerActionResult(
        text=f"Execution `{execution.id}` status: `{result['status']}`.{next_step}",
        changed_client_ids=(execution.client_id,),
    )


def _review_or_verify_execution(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    execution, error = _scoped_execution(database, action.execution_id, mapped_client)
    if error is not None:
        return error
    task = database.get(models.Task, execution.task_id)
    if task is None or task.client_id != execution.client_id:
        return SlackOwnerActionResult(
            text="The execution is not linked to a valid client task.",
            changed_client_ids=(),
        )
    files = ", ".join(execution.simulated_changed_files[:8]) or "None recorded"
    tests = ", ".join(
        f"{item.get('name', 'test')}: {item.get('status', 'unknown')}"
        for item in execution.simulated_test_results[:8]
    ) or "None recorded"
    summary = str((execution.evidence or {}).get("summary") or "No summary recorded")
    if action.action_type == "review_execution":
        record_event(
            database,
            "slack_execution_reviewed",
            actor=f"slack:{slack_user_id}",
            client_id=execution.client_id,
            record_type="execution",
            record_id=execution.id,
            details={"slack_event_id": event_id, "status": execution.status},
        )
        return SlackOwnerActionResult(
            text=(
                f"*Execution review: `{execution.id}`*\n"
                f"• Task: `{task.id}` - {task.requested_outcome}\n"
                f"• Status: `{execution.status}`\n"
                f"• Summary: {summary}\n"
                f"• Files/output: {files}\n"
                f"• Tests: {tests}\n"
                f"If this evidence is correct and complete, use `confirm verify execution {execution.id}`."
            ),
            changed_client_ids=(),
        )

    reviewed = database.scalar(
        select(models.AuditEvent.id).where(
            models.AuditEvent.event_type == "slack_execution_reviewed",
            models.AuditEvent.record_id == execution.id,
            models.AuditEvent.actor == f"slack:{slack_user_id}",
        )
    )
    if reviewed is None:
        return SlackOwnerActionResult(
            text=f"Review the saved evidence first with `review execution {execution.id}`.",
            changed_client_ids=(),
        )
    review_evidence = [summary]
    review_evidence.extend(f"Changed output: {path}" for path in execution.simulated_changed_files[:8])
    review_evidence.extend(
        f"Test {item.get('name', 'test')}: {item.get('status', 'unknown')}"
        for item in execution.simulated_test_results[:8]
    )
    from fastapi import HTTPException
    from app.routes.verifications import review_execution

    try:
        decision, reused = review_execution(
            database,
            execution.id,
            schemas.ExecutionVerificationCreate(
                decision_key=f"slack-verify-{event_id[-24:]}",
                outcome="verified",
                reviewer=f"Slack owner {slack_user_id}",
                explanation="Agency owner reviewed the saved execution evidence and confirmed verification from Slack.",
                review_evidence=review_evidence,
                correct_client_confirmed=True,
                approved_task_followed=True,
                output_exists=True,
                result_matches_requested_outcome=True,
                no_unexpected_changes=True,
            ),
        )
    except HTTPException as verification_error:
        return SlackOwnerActionResult(
            text=f"Execution was not verified: {verification_error.detail}.",
            changed_client_ids=(),
        )
    record_event(
        database,
        "slack_execution_verified",
        actor=f"slack:{slack_user_id}",
        client_id=execution.client_id,
        record_type="verification",
        record_id=decision.id,
        details={"slack_event_id": event_id, "execution_id": execution.id, "reused": reused},
    )
    return SlackOwnerActionResult(
        text=f"Execution `{execution.id}` is verified. Task `{task.id}` and its source finding were updated.",
        changed_client_ids=(execution.client_id,),
    )


def _run_health_check(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if mapped_client is None:
        return SlackOwnerActionResult(
            text="Run a health check from the client's mapped Slack channel.",
            changed_client_ids=(),
        )
    from app.routes.health_checks import run_health_check

    check, findings = run_health_check(
        database,
        mapped_client.id,
        action.website_status if action.website_status in {"available", "unavailable", "unknown"} else "unknown",
    )
    record_event(
        database,
        "slack_health_check_run",
        actor=f"slack:{slack_user_id}",
        client_id=mapped_client.id,
        record_type="health_check",
        record_id=check.id,
        details={"slack_event_id": event_id, "finding_count": len(findings)},
    )
    titles = ", ".join(finding.title for finding in findings[:5]) or "None"
    return SlackOwnerActionResult(
        text=(
            f"Health check `{check.id}` status: `{check.overall_status}`. "
            f"Findings: {len(findings)} ({titles})."
        ),
        changed_client_ids=(mapped_client.id,),
    )


def _sync_website_metrics(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if mapped_client is not None:
        return SlackOwnerActionResult(
            text="Portfolio website metrics sync is agency-wide. Run it from an agency channel.",
            changed_client_ids=(),
        )
    from fastapi import HTTPException
    from app.routes.website_metrics import sync_metrics

    try:
        result = sync_metrics(
            schemas.WebsiteMetricSyncRequest(window_days=action.window_days or 30),
            database,
        )
    except HTTPException as sync_error:
        return SlackOwnerActionResult(
            text=f"Website metrics sync failed: {sync_error.detail}.",
            changed_client_ids=(),
        )
    snapshot_count = len(result["snapshots"])
    unmatched_count = len(result["unmatched_tracker_sites"])
    record_event(
        database,
        "slack_website_metrics_synced",
        actor=f"slack:{slack_user_id}",
        record_type="website_metrics_sync",
        record_id=event_id,
        details={
            "slack_event_id": event_id,
            "window_days": action.window_days or 30,
            "snapshot_count": snapshot_count,
            "unmatched_count": unmatched_count,
        },
    )
    return SlackOwnerActionResult(
        text=(
            f"Website metrics sync saved/reused `{snapshot_count}` snapshots. "
            f"Unmatched tracker sites: `{unmatched_count}`."
        ),
        changed_client_ids=(),
    )


def _sync_search_console(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if mapped_client is None:
        return SlackOwnerActionResult(
            text="Run Search Console sync from the client's mapped Slack channel.",
            changed_client_ids=(),
        )
    from fastapi import HTTPException
    from app.routes.search_console import sync_search_console

    end_date = date.today()
    try:
        snapshots = sync_search_console(
            mapped_client.id,
            schemas.SearchConsoleSyncRequest(
                start_date=end_date - timedelta(days=action.window_days or 28),
                end_date=end_date,
            ),
            database,
        )
    except HTTPException as sync_error:
        return SlackOwnerActionResult(
            text=f"Search Console sync failed: {sync_error.detail}.",
            changed_client_ids=(),
        )
    record_event(
        database,
        "slack_search_console_synced",
        actor=f"slack:{slack_user_id}",
        client_id=mapped_client.id,
        record_type="search_console_sync",
        record_id=event_id,
        details={"slack_event_id": event_id, "snapshot_count": len(snapshots)},
    )
    return SlackOwnerActionResult(
        text=f"Search Console sync saved `{len(snapshots)}` live metric snapshots.",
        changed_client_ids=(mapped_client.id,),
    )


def _handle_notification(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    notification = (
        database.get(models.Notification, action.notification_id)
        if action.notification_id
        else None
    )
    if notification is None:
        return SlackOwnerActionResult(
            text=f"I couldn't find notification `{action.notification_id}`.",
            changed_client_ids=(),
        )
    if mapped_client is not None and notification.client_id != mapped_client.id:
        return SlackOwnerActionResult(
            text="That notification belongs to a different client. Use the correct client channel.",
            changed_client_ids=(),
        )
    from fastapi import HTTPException

    if action.action_type == "mark_notification_read":
        from app.routes.notifications import mark_notification_read

        saved = mark_notification_read(notification.id, database)
        status = "read" if saved.is_read else "unread"
    else:
        from app.routes.slack import retry_slack_delivery

        try:
            delivery = retry_slack_delivery(notification.id, database)
        except HTTPException as retry_error:
            return SlackOwnerActionResult(
                text=f"Notification retry failed: {retry_error.detail}.",
                changed_client_ids=(),
            )
        status = delivery.status
    record_event(
        database,
        "slack_notification_controlled",
        actor=f"slack:{slack_user_id}",
        client_id=notification.client_id,
        record_type="notification",
        record_id=notification.id,
        details={
            "slack_event_id": event_id,
            "action": action.action_type,
            "status": status,
        },
    )
    return SlackOwnerActionResult(
        text=f"Notification `{notification.id}` status: `{status}`.",
        changed_client_ids=(notification.client_id,),
    )


def _run_due_jobs(
    database: Session,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if mapped_client is not None:
        return SlackOwnerActionResult(
            text="Due-job execution is agency-wide. Run it from an agency channel.",
            changed_client_ids=(),
        )
    from app.job_service import run_due_jobs

    results = run_due_jobs(database)
    failed = [result for result in results if result["status"] == "failed"]
    record_event(
        database,
        "slack_due_jobs_run",
        actor=f"slack:{slack_user_id}",
        record_type="scheduled_job_run",
        record_id=event_id,
        details={
            "slack_event_id": event_id,
            "run_count": len(results),
            "failed_count": len(failed),
        },
    )
    return SlackOwnerActionResult(
        text=f"Ran `{len(results)}` due jobs; `{len(failed)}` failed.",
        changed_client_ids=(),
    )


def _set_workflow(
    database: Session,
    action: SlackOwnerAction,
    *,
    slack_user_id: str,
    event_id: str,
    mapped_client: models.Client | None,
) -> SlackOwnerActionResult:
    if mapped_client is None or action.workflow not in {
        "health_check",
        "website_metrics_sync",
        "search_console_sync",
        "daily_client_plan",
    }:
        return SlackOwnerActionResult(
            text="Workflow controls must name a supported workflow from a mapped client channel.",
            changed_client_ids=(),
        )
    job = database.scalar(
        select(models.ScheduledJob).where(
            models.ScheduledJob.client_id == mapped_client.id,
            models.ScheduledJob.job_type == action.workflow,
        )
    )
    interval = {
        "health_check": 10080,
        "website_metrics_sync": 1440,
        "search_console_sync": 1440,
        "daily_client_plan": 1440,
    }[action.workflow]
    if job is None:
        job = models.ScheduledJob(
            job_key=f"{action.workflow}:{mapped_client.id}",
            job_type=action.workflow,
            client_id=mapped_client.id,
            interval_minutes=interval,
            next_run_at=datetime.utcnow(),
            enabled=bool(action.enabled),
            parameters=(
                {
                    "depth": action.workflow_depth or "simple",
                    "focus": "all",
                    "create_report": False,
                    "create_tasks": action.workflow_create_tasks,
                    "report_type": "internal",
                }
                if action.workflow == "daily_client_plan"
                else {}
            ),
        )
        database.add(job)
    else:
        job.enabled = bool(action.enabled)
        if action.workflow == "daily_client_plan":
            job.parameters = {
                **(job.parameters or {}),
                "depth": action.workflow_depth or (job.parameters or {}).get("depth", "simple"),
                "focus": (job.parameters or {}).get("focus", "all"),
                "create_report": bool((job.parameters or {}).get("create_report", False)),
                "create_tasks": bool((job.parameters or {}).get("create_tasks", False)) or action.workflow_create_tasks,
                "report_type": (job.parameters or {}).get("report_type", "internal"),
            }
        if job.enabled and job.next_run_at is None:
            job.next_run_at = datetime.utcnow()
    state = "enabled" if job.enabled else "disabled"
    record_event(
        database,
        "slack_workflow_controlled",
        actor=f"slack:{slack_user_id}",
        client_id=mapped_client.id,
        record_type="scheduled_job",
        record_id=job.id or f"{action.workflow}:{mapped_client.id}",
        details={
            "slack_event_id": event_id,
            "job_type": action.workflow,
            "enabled": job.enabled,
            "create_tasks": bool((job.parameters or {}).get("create_tasks", False)),
        },
    )
    task_note = (
        " Proposed recommendations will become approval-required tasks; no external work will start."
        if action.workflow == "daily_client_plan" and bool((job.parameters or {}).get("create_tasks", False))
        else ""
    )
    return SlackOwnerActionResult(
        text=f"`{action.workflow}` is now `{state}` for `{mapped_client.business_name}`.{task_note}",
        changed_client_ids=(mapped_client.id,),
    )
