---
title: Notifications
slug: notifications
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - Slack notifications
  - dashboard notifications
  - workflow alerts
owner: agency
review_required: true
---

# Notifications

## Purpose

Max sends notifications only when the agency may need to make a decision or take action.

## Notify for

- Approval required
- Critical health issue
- Task failure
- Verification failure
- Missing required access
- Cost threshold exceeded
- Meaningful performance change
- Scheduled report available

## Do not notify for

- Healthy checks
- Normal background processing
- Repeated duplicate findings
- Small unimportant changes
- Successful routine operations requiring no action

## Notification record

Every notification includes:

- Client
- Category
- Importance
- Short explanation
- Requested action
- Related record
- Creation time
- Read status
- Delivery status

## Duplicate prevention

Max must prevent duplicate notifications for the same unresolved event.

Repeated detection updates or links to the existing notification instead of creating unlimited copies.

## Delivery

Slack is the current delivery channel. The notification record remains in Max even if Slack is unavailable.

Temporary delivery failures may retry. Permanent failures create an internal delivery issue.

## Final checklist

- Does this require action?
- Correct client?
- Correct category and importance?
- Related record linked?
- Duplicate event checked?
- Requested action clear?
- Delivery and read status recorded?

