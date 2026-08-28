"""The CLI is the executor's whole interface: JSON in, JSON out."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from helpers import WorkspaceCase  # noqa: E402

from aidlc import cli  # noqa: E402
from aidlc.state import Snapshot  # noqa: E402


class CommandLine(WorkspaceCase):
    def run_cli(self, *argv: str) -> tuple:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["--root", str(self.root), *argv])
        text = buffer.getvalue()
        return code, (json.loads(text) if text.strip() else None)

    def test_validate_reports_a_healthy_graph(self) -> None:
        code, payload = self.run_cli("validate")
        self.assertEqual(0, code)
        self.assertTrue(payload["ok"])

    def test_next_prints_one_directive(self) -> None:
        code, payload = self.run_cli("next")
        self.assertEqual(0, code)
        self.assertEqual("RECORD_AUDIT", payload["kind"])
        self.assertIn("directive_id", payload)
        self.assertIn("state_hash", payload)
        self.assertIn("settles", payload)

    def test_record_settles_the_directive(self) -> None:
        _, directive = self.run_cli("next")
        fields = json.dumps({"user_input": "hi", "ai_response": "ok", "context": "initial"})
        code, payload = self.run_cli(
            "record",
            "--directive-id", directive["directive_id"],
            "--state-hash", directive["state_hash"],
            "--kind", "interaction",
            "--fields-json", fields,
        )
        self.assertEqual(0, code)
        self.assertEqual("interaction", payload["recorded"][0]["kind"])
        _, nxt = self.run_cli("next")
        self.assertEqual("RUN_STAGE", nxt["kind"])

    def test_record_with_a_stale_hash_exits_nonzero_with_a_typed_error(self) -> None:
        _, directive = self.run_cli("next")
        self.settle(self.next_directive())
        code, payload = self.run_cli(
            "record",
            "--directive-id", directive["directive_id"],
            "--state-hash", directive["state_hash"],
            "--kind", "interaction",
            "--field", "user_input=hi", "--field", "ai_response=ok", "--field", "context=x",
        )
        self.assertEqual(2, code)
        self.assertEqual("StaleDirective", payload["error"])

    def test_status_projects_the_plan_and_the_checks(self) -> None:
        code, payload = self.run_cli("status")
        self.assertEqual(0, code)
        self.assertEqual(Snapshot.capture(self.root).state_hash, payload["state_hash"])
        self.assertTrue(payload["plan"])
        self.assertIn("audit.initial_request", [c["id"] for c in payload["blocking"]])

    def test_rebuild_reports_the_event_count(self) -> None:
        self.settle(self.next_directive())
        code, payload = self.run_cli("rebuild")
        self.assertEqual(0, code)
        self.assertEqual(1, payload["rebuilt_events"])


if __name__ == "__main__":
    unittest.main()
