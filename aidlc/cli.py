"""Command line surface: `python -m aidlc ...`.

Two commands matter:

    aidlc next                 -> print the single directive for this turn (read-only)
    aidlc record --kind ...    -> settle that directive with exactly one event

Everything is JSON on stdout so the executor can parse it without a library.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import checks, engine, recorder, stages
from .model import AidlcError, EventKind
from .state import Snapshot


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.handler
    try:
        return handler(args)
    except AidlcError as exc:
        _emit({"error": type(exc).__name__, "message": str(exc)})
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aidlc", description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="workspace root (default: .)")
    sub = parser.add_subparsers(dest="command", required=True)

    nxt = sub.add_parser("next", help="print the one directive for this turn")
    nxt.set_defaults(handler=_cmd_next)

    init = sub.add_parser("init", help="create the internal ledger directory and audit header")
    init.set_defaults(handler=_cmd_init)

    rec = sub.add_parser("record", help="settle the current directive with one event")
    rec.add_argument("--directive-id", required=True)
    rec.add_argument("--state-hash", required=True)
    rec.add_argument("--kind", required=True, choices=[e.value for e in EventKind])
    rec.add_argument("--field", action="append", default=[], metavar="NAME=VALUE",
                     help="event field; repeatable. Use --fields-json for structured values.")
    rec.add_argument("--fields-json", help="event fields as a JSON object, or '-' for stdin")
    rec.set_defaults(handler=_cmd_record)

    status = sub.add_parser("status", help="print the lifecycle projection and check results")
    status.set_defaults(handler=_cmd_status)

    rebuild = sub.add_parser("rebuild", help="regenerate audit.md and aidlc-state.md from ledger")
    rebuild.set_defaults(handler=_cmd_rebuild)

    validate = sub.add_parser("validate", help="structural self-check of the stage graph")
    validate.set_defaults(handler=_cmd_validate)
    return parser


def _cmd_next(args: argparse.Namespace) -> int:
    directive = engine.step(args.root)
    _emit(directive.to_dict())
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    recorder.initialize(args.root)
    _emit({"initialized": str(Path(args.root).resolve())})
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    fields: Dict[str, Any] = {}
    if args.fields_json:
        raw = sys.stdin.read() if args.fields_json == "-" else args.fields_json
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise SystemExit("--fields-json must be a JSON object")
        fields.update(parsed)
    for pair in args.field:
        name, _, value = pair.partition("=")
        fields[name] = value
    result = recorder.record(
        root=args.root,
        directive_id=args.directive_id,
        expect_state_hash=args.state_hash,
        kind=EventKind(args.kind),
        fields=fields,
    )
    _emit({
        "recorded": [e.to_dict() for e in result.events],
        "state_hash": result.state_hash,
    })
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    snapshot = Snapshot.capture(args.root)
    results = checks.run_all(snapshot)
    _emit({
        "state_hash": snapshot.state_hash,
        "plan": list(engine.plan(snapshot)),
        "blocking": [c.to_dict() for c in checks.blocking(results)],
        "advisories": [c.to_dict() for c in checks.advisories(results)],
    })
    return 0


def _cmd_rebuild(args: argparse.Namespace) -> int:
    count = recorder.rebuild(args.root)
    _emit({"rebuilt_events": count})
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    problems: List[str] = stages.validate_graph()
    _emit({"problems": problems, "ok": not problems})
    return 0 if not problems else 1


def _emit(payload: Any) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
