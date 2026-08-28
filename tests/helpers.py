"""Shared test helpers: a scripted executor that obeys directives."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aidlc import engine, recorder  # noqa: E402
from aidlc.model import Directive, EventKind  # noqa: E402
from aidlc.state import Snapshot  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


class WorkspaceCase(unittest.TestCase):
    """A temporary workspace with an initialized recorder."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="aidlc-test-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        recorder.initialize(self.root)

    # -- driving ------------------------------------------------------------

    def next_directive(self) -> Directive:
        return engine.step(self.root)

    def settle(
        self,
        directive: Directive,
        kind: Optional[EventKind] = None,
        fields: Optional[Dict[str, Any]] = None,
        write_artifacts: bool = True,
    ) -> None:
        kind = kind or directive.settles[0]
        fields = dict(fields) if fields is not None else self.default_fields(directive, kind)
        if write_artifacts:
            self.write_expected(directive, kind)
        snapshot = Snapshot.capture(self.root)
        recorder.record(self.root, directive.id, snapshot.state_hash, kind, fields)

    def default_fields(self, directive: Directive, kind: EventKind) -> Dict[str, Any]:
        path = str(directive.payload.get("path", ""))
        by_kind: Dict[EventKind, Dict[str, Any]] = {
            EventKind.INTERACTION: {
                "user_input": "build a todo api",
                "ai_response": "acknowledged",
                "context": "initial request",
            },
            EventKind.QUESTIONS_PUBLISHED: {"path": path},
            EventKind.ANSWERS_RECEIVED: {"path": path, "user_input": "A"},
            EventKind.ASSESSMENT: {"include": True, "rationale": "needed"},
            EventKind.APPROVAL_RESPONSE: {
                "user_input": "Continue to Next Stage",
                "decision": "approve",
            },
            EventKind.STAGE_COMPLETED: {"summary": "done"},
            EventKind.STAGE_SKIPPED: {"reason": "assessed out"},
            EventKind.WORKFLOW_COMPLETED: {"summary": "all stages settled"},
            EventKind.RECOVERY: {"issue": "x", "steps": "y", "outcome": "z"},
            EventKind.CHANGE_CONFIRMED: {"request": "r", "user_input": "yes", "action": "apply"},
            EventKind.HUMAN_TASK: {"description": "done", "resolved": True},
            EventKind.RESUME: {"summary": "resumed"},
        }
        return by_kind[kind]

    def write_expected(self, directive: Directive, kind: EventKind) -> None:
        if kind is EventKind.QUESTIONS_PUBLISHED:
            self.write(directive.payload["path"], "## Q1\n\nA) yes\n\n[Answer]: A\n")
        if kind is EventKind.STAGE_COMPLETED:
            for rel in directive.payload.get("required_artifacts", []):
                self.write(rel, f"# {Path(rel).stem}\n\n- [x] step one\n")

    def write(self, relpath: str, content: str) -> Path:
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def run_lifecycle(
        self,
        include: bool = True,
        units: Optional[List[str]] = None,
        max_turns: int = 200,
    ) -> List[Directive]:
        """Drive the engine to HALT_COMPLETE, answering every directive."""

        seen: List[Directive] = []
        for _ in range(max_turns):
            directive = self.next_directive()
            seen.append(directive)
            if directive.kind.value == "HALT_COMPLETE":
                return seen
            kind = directive.settles[0]
            fields = self.default_fields(directive, kind)
            if kind is EventKind.ASSESSMENT:
                fields = {"include": include, "rationale": "scripted"}
            if units and directive.stage == "units_generation" \
                    and kind is EventKind.STAGE_COMPLETED:
                fields = dict(fields, units=units)
            self.settle(directive, kind, fields)
        raise AssertionError("lifecycle did not terminate")
