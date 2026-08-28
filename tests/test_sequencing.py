"""Sequencing: the engine decides what happens next, in the source's order."""

from __future__ import annotations

import unittest
from typing import List

from helpers import WorkspaceCase  # noqa: E402

from aidlc import engine, stages  # noqa: E402
from aidlc.model import DirectiveKind, EventKind, Policy  # noqa: E402
from aidlc.state import Snapshot  # noqa: E402


class StageGraph(unittest.TestCase):
    def test_graph_is_structurally_valid(self) -> None:
        self.assertEqual([], stages.validate_graph())

    def test_source_stage_set_is_preserved(self) -> None:
        self.assertEqual(
            [
                "workspace_detection", "reverse_engineering", "requirements_analysis",
                "user_stories", "workflow_planning", "application_design", "units_generation",
                "functional_design", "nfr_requirements", "nfr_design", "infrastructure_design",
                "code_generation", "build_and_test", "operations",
            ],
            list(stages.ORDER),
        )

    def test_always_stages_match_the_source(self) -> None:
        always = [s.id for s in stages.STAGES if s.policy is Policy.ALWAYS]
        self.assertEqual(
            ["workspace_detection", "requirements_analysis", "workflow_planning",
             "code_generation", "build_and_test"],
            always,
        )

    def test_construction_gates_offer_exactly_two_options(self) -> None:
        self.assertEqual(("Request Changes", "Continue to Next Stage"),
                         stages.COMPLETION_OPTIONS)


class TurnOrder(WorkspaceCase):
    def kinds(self, directives) -> List[str]:
        return [d.kind.value for d in directives]

    def test_first_move_is_logging_the_raw_request(self) -> None:
        directive = self.next_directive()
        self.assertIs(DirectiveKind.RECORD_AUDIT, directive.kind)
        self.assertTrue(directive.payload["verbatim_required"])

    def test_workspace_detection_runs_before_anything_else(self) -> None:
        self.settle(self.next_directive())
        directive = self.next_directive()
        self.assertEqual("workspace_detection", directive.stage)

    def test_conditional_stage_is_assessed_before_it_runs(self) -> None:
        self.settle(self.next_directive())
        self.settle(self.next_directive())
        directive = self.next_directive()
        self.assertIs(DirectiveKind.ASSESS_CONDITIONAL, directive.kind)
        self.assertEqual("reverse_engineering", directive.stage)
        self.assertTrue(directive.payload["include_criteria"])
        self.assertEqual("include", directive.payload["default_on_doubt"])

    def test_assessed_out_stage_is_skipped_explicitly(self) -> None:
        self.settle(self.next_directive())
        self.settle(self.next_directive())
        assess = self.next_directive()
        self.settle(assess, EventKind.ASSESSMENT, {"include": False, "rationale": "greenfield"})
        directive = self.next_directive()
        self.assertIs(DirectiveKind.SKIP_STAGE, directive.kind)
        self.assertEqual("reverse_engineering", directive.stage)

    def test_questions_precede_the_stage_and_answers_gate_it(self) -> None:
        seen = []
        for _ in range(8):
            directive = self.next_directive()
            seen.append(directive)
            if directive.stage == "requirements_analysis" \
                    and directive.kind is DirectiveKind.RUN_STAGE:
                break
            self.settle(directive)
        kinds = self.kinds([d for d in seen if d.stage == "requirements_analysis"])
        self.assertEqual(["ASK_QUESTIONS", "AWAIT_ANSWERS", "RUN_STAGE"], kinds)

    def test_answer_file_uses_the_source_answer_tag(self) -> None:
        for _ in range(8):
            directive = self.next_directive()
            if directive.kind is DirectiveKind.ASK_QUESTIONS:
                self.assertEqual("[Answer]:", directive.payload["answer_tag"])
                self.assertTrue(directive.payload["path"].endswith(".md"))
                return
            self.settle(directive)
        self.fail("no ASK_QUESTIONS directive was emitted")

    def test_skipped_prerequisite_skips_its_dependent_automatically(self) -> None:
        skipped = []
        for directive in self.run_lifecycle(include=False):
            if directive.kind is DirectiveKind.SKIP_STAGE:
                skipped.append((directive.stage, directive.payload["rationale"]))
        automatic = [s for s, reason in skipped if "was skipped" in reason]
        self.assertIn("nfr_design", automatic)

    def test_per_unit_stages_complete_one_unit_before_the_next(self) -> None:
        directives = self.run_lifecycle(include=True, units=["auth", "billing"])
        order = [
            (d.stage, d.unit) for d in directives
            if d.unit and d.kind is DirectiveKind.RUN_STAGE
        ]
        units_in_order = [unit for _, unit in order]
        self.assertEqual(sorted(set(units_in_order)), ["auth", "billing"])
        self.assertEqual(units_in_order, sorted(units_in_order, key=lambda u: u != "auth"))

    def test_code_generation_plans_then_generates(self) -> None:
        parts = [
            d.part for d in self.run_lifecycle()
            if d.stage == "code_generation" and d.kind is DirectiveKind.RUN_STAGE
        ]
        self.assertEqual(["planning", "generation"], parts)

    def test_build_and_test_runs_after_every_unit(self) -> None:
        directives = self.run_lifecycle(include=True, units=["auth", "billing"])
        kinds = [(d.stage, d.unit) for d in directives]
        build_index = next(i for i, (stage, _) in enumerate(kinds) if stage == "build_and_test")
        later_units = [s for s, u in kinds[build_index:] if u]
        self.assertEqual([], later_units)

    def test_lifecycle_terminates_with_halt_complete(self) -> None:
        directives = self.run_lifecycle()
        self.assertIs(DirectiveKind.HALT_COMPLETE, directives[-1].kind)

    def test_operations_is_a_placeholder_and_never_scheduled(self) -> None:
        stage_ids = {d.stage for d in self.run_lifecycle()}
        self.assertNotIn("operations", stage_ids)


class OpenItemsTakePrecedence(WorkspaceCase):
    def advance_past_bootstrap(self) -> None:
        self.settle(self.next_directive())
        self.settle(self.next_directive())

    def test_unconfirmed_change_request_outranks_stage_work(self) -> None:
        self.advance_past_bootstrap()
        directive = self.next_directive()
        self.settle(directive, EventKind.ASSESSMENT, {"include": False, "rationale": "no"})
        skip = self.next_directive()
        self.settle(skip)
        # Inject a change request by settling the next directive with a change event.
        pending = self.next_directive()
        self.assertNotIn(EventKind.CHANGE_REQUEST, pending.settles)
        self.append_change_request()
        directive = self.next_directive()
        self.assertIs(DirectiveKind.CONFIRM_CHANGE, directive.kind)
        self.assertTrue(directive.payload["request"])

    def test_open_human_task_escalates(self) -> None:
        self.advance_past_bootstrap()
        self.append_event(EventKind.HUMAN_TASK, {"description": "create the cloud account"})
        directive = self.next_directive()
        self.assertIs(DirectiveKind.ESCALATE_HUMAN, directive.kind)
        self.assertIn("cloud account", directive.payload["description"])

    def test_paused_workflow_resumes_before_it_proceeds(self) -> None:
        self.advance_past_bootstrap()
        self.append_event(EventKind.PAUSE, {"reason": "user stepped away"})
        directive = self.next_directive()
        self.assertIs(DirectiveKind.RESUME_SESSION, directive.kind)
        self.assertTrue(directive.payload["welcome_back"])

    # -- helpers ------------------------------------------------------------

    def append_change_request(self) -> None:
        self.append_event(EventKind.CHANGE_REQUEST,
                          {"request": "switch to postgres", "impact": "requirements onwards",
                           "target_stage": "requirements_analysis"})

    def append_event(self, kind: EventKind, fields: dict) -> None:
        import json

        from aidlc.state import LEDGER_PATH

        entry = {
            "kind": kind.value,
            "timestamp": "2025-01-01T00:00:00+00:00",
            "directive_id": "external",
            "stage": None,
            "unit": None,
            "fields": fields,
        }
        path = self.root / LEDGER_PATH
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")


class ContextLoading(WorkspaceCase):
    def test_directives_name_the_artifacts_to_load(self) -> None:
        for directive in self.run_lifecycle():
            if directive.kind is DirectiveKind.RUN_STAGE and directive.stage == "build_and_test":
                self.assertTrue(any("code" in p for p in directive.context_to_load))
                return
        self.fail("build_and_test never ran")

    def test_plan_projection_covers_every_non_placeholder_stage(self) -> None:
        snapshot = Snapshot.capture(self.root)
        projected = {row["stage"] for row in engine.plan(snapshot)}
        expected = {s.id for s in stages.STAGES if s.policy is not Policy.PLACEHOLDER}
        self.assertEqual(expected, projected)


if __name__ == "__main__":
    unittest.main()
