"""The recorder is the sole writer and the concurrency boundary."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from helpers import WorkspaceCase  # noqa: E402

from aidlc import artifacts, recorder  # noqa: E402
from aidlc.model import (  # noqa: E402
    ConcurrentWrite,
    EventKind,
    InvalidEvent,
    StaleDirective,
    UnknownDirective,
)
from aidlc.state import LEDGER_PATH, Snapshot  # noqa: E402


class RecorderContract(WorkspaceCase):
    def test_rejects_an_event_the_directive_does_not_settle(self) -> None:
        directive = self.next_directive()
        snapshot = Snapshot.capture(self.root)
        with self.assertRaises(InvalidEvent):
            recorder.record(self.root, directive.id, snapshot.state_hash,
                            EventKind.STAGE_COMPLETED, {"summary": "sneaking ahead"})

    def test_rejects_an_event_missing_mandatory_fields(self) -> None:
        directive = self.next_directive()
        snapshot = Snapshot.capture(self.root)
        with self.assertRaises(InvalidEvent):
            recorder.record(self.root, directive.id, snapshot.state_hash,
                            EventKind.INTERACTION, {"user_input": "hi"})

    def test_rejects_a_substituted_directive(self) -> None:
        directive = self.next_directive()
        snapshot = Snapshot.capture(self.root)
        with self.assertRaises(UnknownDirective):
            recorder.record(self.root, "deadbeefdeadbeef", snapshot.state_hash,
                            directive.settles[0],
                            self.default_fields(directive, directive.settles[0]))

    def test_rejects_a_stale_directive_after_the_world_moved(self) -> None:
        first = self.next_directive()
        stale_hash = Snapshot.capture(self.root).state_hash
        self.settle(first)
        with self.assertRaises(StaleDirective):
            recorder.record(self.root, first.id, stale_hash, first.settles[0],
                            self.default_fields(first, first.settles[0]))

    def test_accepted_event_is_appended_to_the_ledger_and_audit(self) -> None:
        directive = self.next_directive()
        self.settle(directive)
        lines = (self.root / LEDGER_PATH).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(1, len(lines))
        entry = json.loads(lines[0])
        self.assertEqual(directive.id, entry["directive_id"])
        self.assertIn("build a todo api", (self.root / artifacts.AUDIT_PATH)
                      .read_text(encoding="utf-8"))

    def test_audit_is_append_only(self) -> None:
        self.settle(self.next_directive())
        first = (self.root / artifacts.AUDIT_PATH).read_text(encoding="utf-8")
        self.settle(self.next_directive())
        second = (self.root / artifacts.AUDIT_PATH).read_text(encoding="utf-8")
        self.assertTrue(second.startswith(first))

    def test_stage_started_is_derived_once(self) -> None:
        self.settle(self.next_directive())
        run_stage = self.next_directive()
        self.settle(run_stage)
        kinds = [json.loads(line)["kind"]
                 for line in (self.root / LEDGER_PATH).read_text(encoding="utf-8").splitlines()]
        self.assertEqual(["interaction", "stage_started", "stage_completed"], kinds)

    def test_approval_closes_the_stage_as_the_directive_declares(self) -> None:
        directives = []
        for _ in range(12):
            directive = self.next_directive()
            directives.append(directive)
            if directive.kind.value == "AWAIT_APPROVAL":
                self.assertTrue(directive.payload["on_approval"]["complete_stage"])
                self.settle(directive)
                snapshot = Snapshot.capture(self.root)
                self.assertIsNotNone(directive.stage)
                self.assertTrue(snapshot.completed(str(directive.stage), directive.unit))
                return
            self.settle(directive)
        self.fail("no approval gate was reached")

    def test_rebuild_regenerates_the_audit_from_the_ledger(self) -> None:
        self.settle(self.next_directive())
        self.settle(self.next_directive())
        original = (self.root / artifacts.AUDIT_PATH).read_text(encoding="utf-8")
        (self.root / artifacts.AUDIT_PATH).write_text("# clobbered\n", encoding="utf-8")
        count = recorder.rebuild(self.root)
        self.assertGreater(count, 1)
        self.assertEqual(original, (self.root / artifacts.AUDIT_PATH).read_text(encoding="utf-8"))

    def test_lock_prevents_a_second_writer(self) -> None:
        lock = Path(self.root / recorder.LOCK_PATH)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("999999", encoding="utf-8")
        directive = self.next_directive()
        with self.assertRaises(ConcurrentWrite):
            recorder.record(self.root, directive.id,
                            Snapshot.capture(self.root).state_hash,
                            directive.settles[0],
                            self.default_fields(directive, directive.settles[0]))


if __name__ == "__main__":
    unittest.main()
