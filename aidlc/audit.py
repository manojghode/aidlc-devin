"""Audit rendering.

The Markdown log formats are ported from the source's audit-logging rules:
verbatim user input, one section per event, append-only, never overwritten.

Standard library only.
"""

from __future__ import annotations

from typing import Any, List, Mapping

from .model import AuditEvent, EventKind

HEADER = """# AI-DLC Audit Log

Append-only. Every entry is written by the recorder; nothing here is ever
rewritten or deleted. User input is recorded verbatim.

"""

_TITLES: Mapping[EventKind, str] = {
    EventKind.INTERACTION: "Interaction",
    EventKind.STAGE_STARTED: "Stage Started",
    EventKind.STAGE_COMPLETED: "Stage Completed",
    EventKind.STAGE_SKIPPED: "Stage Skipped",
    EventKind.STAGE_RESTARTED: "Stage Restarted",
    EventKind.ASSESSMENT: "Conditional Assessment",
    EventKind.APPROVAL_PROMPT: "Approval Prompt",
    EventKind.APPROVAL_RESPONSE: "Approval Response",
    EventKind.QUESTIONS_PUBLISHED: "Questions Published",
    EventKind.ANSWERS_RECEIVED: "Answers Received",
    EventKind.AMBIGUITY_DETECTED: "Ambiguity Detected",
    EventKind.AMBIGUITY_RESOLVED: "Ambiguity Resolved",
    EventKind.ERROR: "Error",
    EventKind.RECOVERY: "Recovery",
    EventKind.CHANGE_REQUEST: "Change Request",
    EventKind.CHANGE_CONFIRMED: "Change Confirmed",
    EventKind.EXTENSION_DECISION: "Extension Decision",
    EventKind.EXTENSION_SKIPPED: "Extension Skipped",
    EventKind.EXTENSION_COMPLIANCE: "Extension Compliance",
    EventKind.CONTENT_VALIDATION: "Content Validation",
    EventKind.HUMAN_TASK: "Human Task",
    EventKind.PAUSE: "Workflow Paused",
    EventKind.RESUME: "Workflow Resumed",
    EventKind.WORKFLOW_COMPLETED: "Workflow Completed",
}


def title(kind: EventKind) -> str:
    return _TITLES.get(kind, kind.value.replace("_", " ").title())


def render(event: AuditEvent) -> str:
    """One Markdown section for one event."""

    lines: List[str] = [
        f"## {event.timestamp} — {title(event.kind)}",
        "",
        f"- **Event**: `{event.kind.value}`",
        f"- **Directive**: `{event.directive_id}`",
    ]
    if event.stage:
        lines.append(f"- **Stage**: {event.stage}")
    if event.unit:
        lines.append(f"- **Unit**: {event.unit}")
    for key, value in sorted(event.fields.items()):
        lines.extend(_render_field(key, value))
    lines.append("")
    return "\n".join(lines) + "\n"


def _render_field(key: str, value: Any) -> List[str]:
    label = key.replace("_", " ").title()
    if isinstance(value, str) and ("\n" in value or len(value) > 160):
        return [f"- **{label}**:", "", "```text", value.rstrip("\n"), "```", ""]
    if isinstance(value, (list, tuple)):
        if not value:
            return [f"- **{label}**: (none)"]
        return [f"- **{label}**:"] + [f"  - {item}" for item in value]
    if isinstance(value, Mapping):
        if not value:
            return [f"- **{label}**: (none)"]
        return [f"- **{label}**:"] + [f"  - {k}: {v}" for k, v in sorted(value.items())]
    return [f"- **{label}**: {value}"]
