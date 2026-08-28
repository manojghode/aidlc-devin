"""Manual smoke driver: walks a synthetic project through the engine.

Not part of the test suite; run it with `python tests/smoke.py /tmp/ws` to see
the directive sequence the engine produces.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aidlc import engine, recorder  # noqa: E402
from aidlc.model import EventKind  # noqa: E402
from aidlc.state import Snapshot  # noqa: E402


def answer(root: Path, directive) -> dict:
    kind = directive.settles[0]
    fields = {
        EventKind.INTERACTION: {"user_input": "build a todo api", "ai_response": "ok",
                                "context": "initial request"},
        EventKind.QUESTIONS_PUBLISHED: {"path": directive.payload.get("path", "")},
        EventKind.ANSWERS_RECEIVED: {"path": directive.payload.get("path", ""),
                                     "user_input": "A"},
        EventKind.ASSESSMENT: {"include": False, "rationale": "not needed for this change"},
        EventKind.APPROVAL_RESPONSE: {"user_input": "Continue to Next Stage",
                                      "decision": "approve"},
        EventKind.STAGE_COMPLETED: {"summary": "done"},
        EventKind.STAGE_SKIPPED: {"reason": directive.payload.get("rationale", "skipped")},
        EventKind.WORKFLOW_COMPLETED: {"summary": "done"},
    }.get(kind, {})
    if kind is EventKind.QUESTIONS_PUBLISHED:
        path = root / directive.payload["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("## Q1\n\nA) yes\n\n[Answer]: A\n", encoding="utf-8")
    if kind is EventKind.STAGE_COMPLETED:
        for rel in directive.payload.get("required_artifacts", []):
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                p.write_text(f"# {p.stem}\n\ncontent\n", encoding="utf-8")
    return fields


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/aidlc-smoke").resolve()
    root.mkdir(parents=True, exist_ok=True)
    recorder.initialize(root)
    for turn in range(1, 80):
        directive = engine.step(root)
        print(f"{turn:>3} {directive.kind.value:<20} {directive.stage or '':<24} "
              f"{directive.unit or '':<8} {directive.part or '':<10} {directive.reason}")
        if directive.kind.value == "HALT_COMPLETE":
            return 0
        fields = answer(root, directive)
        if not fields:
            print("  no scripted response for", directive.settles)
            print(json.dumps(directive.to_dict(), indent=2))
            return 1
        snapshot = Snapshot.capture(root)
        recorder.record(root, directive.id, snapshot.state_hash, directive.settles[0], fields)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
