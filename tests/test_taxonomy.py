"""The taxonomies carried over from the source project, verified verbatim."""

from __future__ import annotations

import unittest

from helpers import REPO_ROOT  # noqa: F401,E402  (path bootstrap)

from aidlc import audit  # noqa: E402
from aidlc.model import AuditEvent, DirectiveKind, EventKind  # noqa: E402

SOURCE_EVENT_KINDS = {
    "interaction", "stage_started", "stage_completed", "stage_skipped", "stage_restarted",
    "assessment", "approval_prompt", "approval_response", "questions_published",
    "answers_received", "ambiguity_detected", "ambiguity_resolved", "error", "recovery",
    "change_request", "change_confirmed", "extension_decision", "extension_skipped",
    "extension_compliance", "content_validation", "human_task", "pause", "resume",
    "workflow_completed",
}

SOURCE_DIRECTIVE_KINDS = {
    "RECORD_AUDIT", "RESUME_SESSION", "ASSESS_CONDITIONAL", "RUN_STAGE", "ASK_QUESTIONS",
    "AWAIT_ANSWERS", "AWAIT_APPROVAL", "SKIP_STAGE", "REMEDIATE", "CONFIRM_CHANGE",
    "ESCALATE_HUMAN", "HALT_COMPLETE",
}


class Taxonomy(unittest.TestCase):
    def test_audit_event_kinds_match_the_source(self) -> None:
        self.assertEqual(SOURCE_EVENT_KINDS, {e.value for e in EventKind})

    def test_directive_kinds_match_the_source(self) -> None:
        self.assertEqual(SOURCE_DIRECTIVE_KINDS, {d.value for d in DirectiveKind})

    def test_every_event_kind_has_an_audit_heading(self) -> None:
        for kind in EventKind:
            event = AuditEvent(
                kind=kind,
                timestamp="2025-01-01T00:00:00+00:00",
                directive_id="0" * 16,
                fields={"user_input": "x"},
            )
            rendered = audit.render(event)
            self.assertTrue(rendered.startswith("## 2025-01-01"), kind.value)
            self.assertIn(f"`{kind.value}`", rendered)

    def test_audit_entries_are_self_contained_markdown_sections(self) -> None:
        event = AuditEvent(
            kind=EventKind.STAGE_COMPLETED,
            timestamp="2025-01-01T00:00:00+00:00",
            directive_id="abc",
            stage="requirements_analysis",
            fields={"summary": "done"},
        )
        rendered = audit.render(event)
        self.assertIn("- **Stage**: requirements_analysis", rendered)
        self.assertTrue(rendered.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
