"""Check semantics, ported from the source's error-handling rules."""

from __future__ import annotations

import unittest

from helpers import WorkspaceCase  # noqa: E402

from aidlc import artifacts, checks  # noqa: E402
from aidlc.model import CheckStatus, DirectiveKind, Severity  # noqa: E402
from aidlc.state import Snapshot  # noqa: E402


def result(results, check_id):
    return next(r for r in results if r.id == check_id)


class SeverityLadder(unittest.TestCase):
    def test_critical_and_high_block_medium_and_low_do_not(self) -> None:
        from aidlc.model import CheckResult

        def make(severity: Severity) -> CheckResult:
            return CheckResult(id="x", status=CheckStatus.FAIL, severity=severity)

        self.assertTrue(make(Severity.CRITICAL).blocking)
        self.assertTrue(make(Severity.HIGH).blocking)
        self.assertFalse(make(Severity.MEDIUM).blocking)
        self.assertFalse(make(Severity.LOW).blocking)

    def test_a_passing_check_never_blocks(self) -> None:
        from aidlc.model import CheckResult

        self.assertFalse(
            CheckResult(id="x", status=CheckStatus.PASS, severity=Severity.CRITICAL).blocking
        )


class CheckBehaviour(WorkspaceCase):
    def snapshot(self) -> Snapshot:
        return Snapshot.capture(self.root)

    def test_missing_initial_request_is_critical(self) -> None:
        found = result(checks.run_all(self.snapshot()), "audit.initial_request")
        self.assertIs(CheckStatus.FAIL, found.status)
        self.assertIs(Severity.CRITICAL, found.severity)
        self.assertEqual(DirectiveKind.RECORD_AUDIT.value, found.remediation_kind)

    def test_the_engine_remediates_a_blocking_failure_before_anything_else(self) -> None:
        self.settle(self.next_directive())
        self.settle(self.next_directive())  # workspace detection -> state.md exists
        (self.root / artifacts.STATE_PATH).write_text("", encoding="utf-8")
        directive = self.next_directive()
        self.assertIs(DirectiveKind.REMEDIATE, directive.kind)
        self.assertIn(directive.payload["check"]["id"], {"state.present", "state.parseable"})
        self.assertTrue(directive.payload["recovery"])

    def test_a_rewritten_audit_log_is_detected(self) -> None:
        self.settle(self.next_directive())
        (self.root / artifacts.AUDIT_PATH).write_text("# AI-DLC Audit Log\n", encoding="utf-8")
        found = result(checks.run_all(self.snapshot()), "audit.append_only")
        self.assertIs(CheckStatus.FAIL, found.status)
        self.assertIs(Severity.CRITICAL, found.severity)

    def test_a_blank_answer_tag_leaves_the_question_unanswered(self) -> None:
        for _ in range(8):
            directive = self.next_directive()
            if directive.kind is DirectiveKind.ASK_QUESTIONS:
                self.write(directive.payload["path"], "## Q1\n\nA) yes\n\n[Answer]:\n")
                self.settle(directive, write_artifacts=False)
                break
            self.settle(directive)
        else:
            self.fail("no questions were asked")
        self.assertIs(DirectiveKind.AWAIT_ANSWERS, self.next_directive().kind)

    def test_an_incomplete_plan_blocks_the_stage(self) -> None:
        for _ in range(40):
            directive = self.next_directive()
            plans = [
                p for p in directive.payload.get("required_artifacts", []) if "plan" in p
            ]
            if directive.kind is DirectiveKind.RUN_STAGE and plans and directive.part != "planning":
                for rel in directive.payload["required_artifacts"]:
                    body = "# Plan\n\n- [ ] not done yet\n" if rel in plans else "# doc\n"
                    self.write(rel, body)
                self.settle(directive, write_artifacts=False)
                break
            self.settle(directive)
        else:
            self.skipTest("no plan-bearing stage reached")
        # the gate closes the stage; only then is an unchecked plan a violation
        for _ in range(3):
            directive = self.next_directive()
            if directive.kind is DirectiveKind.REMEDIATE:
                self.assertEqual("plan.checkboxes_complete", directive.payload["check"]["id"])
                found = result(checks.run_all(self.snapshot()), "plan.checkboxes_complete")
                self.assertIs(CheckStatus.FAIL, found.status)
                return
            self.settle(directive)
        self.fail("the incomplete plan was never flagged")

    def test_advisories_do_not_replace_the_directive(self) -> None:
        directives = []
        for _ in range(14):
            directive = self.next_directive()
            directives.append(directive)
            self.settle(directive)
        snapshot = self.snapshot()
        found = result(checks.run_all(snapshot), "extensions.configured")
        self.assertIs(CheckStatus.FAIL, found.status)
        self.assertIs(Severity.MEDIUM, found.severity)
        directive = self.next_directive()
        self.assertIsNot(DirectiveKind.REMEDIATE, directive.kind)
        self.assertIn("extensions.configured", [a.id for a in directive.advisories])

    def test_a_unit_dependency_cycle_is_reported(self) -> None:
        cycle = {"auth": ("billing",), "billing": ("auth",)}
        self.assertIsNotNone(checks._find_cycle(cycle))
        self.assertIsNone(checks._find_cycle({"auth": (), "billing": ("auth",)}))

    def test_every_documented_check_id_is_produced(self) -> None:
        produced = {r.id for r in checks.run_all(self.snapshot())}
        expected = {
            "state.present", "state.parseable", "state.single_current",
            "state.matches_artifacts", "artifacts.present", "questions.answered",
            "questions.unambiguous", "plan.checkboxes_complete", "approval.recorded",
            "units.acyclic", "units.deps_satisfied", "extensions.configured",
            "extensions.compliance", "audit.initial_request", "audit.append_only",
            "content.validated",
        }
        self.assertEqual(set(), expected - produced)


if __name__ == "__main__":
    unittest.main()
