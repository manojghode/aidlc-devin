"""The sole writer.

Nothing else in this package writes to disk. Every accepted event must:

* quote the directive it settles (``directive_id``),
* quote the state hash the directive was computed from (``expect_state_hash``),
* be one of the event kinds that directive declares it ``settles``,
* carry the fields the source's log formats make mandatory.

The recorder re-derives the current directive from the current snapshot before
accepting anything, so an executor cannot substitute a different move: if the
world moved, the recomputed directive id no longer matches.

Standard library only.
"""

from __future__ import annotations

import errno
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

from . import artifacts, audit, engine, statedoc
from .model import (
    AuditEvent,
    ConcurrentWrite,
    Directive,
    DirectiveKind,
    EventKind,
    InvalidEvent,
    StageStatus,
    StaleDirective,
    UnknownDirective,
    required_event_fields,
)
from .state import AUDIT_INDEX_PATH, INTERNAL_DIR, LEDGER_PATH, Snapshot

LOCK_PATH = f"{INTERNAL_DIR}/recorder.lock"


@dataclass(frozen=True)
class RecordResult:
    events: Tuple[AuditEvent, ...]
    state_hash: str
    directive: Directive


def record(
    root: "os.PathLike[str] | str",
    directive_id: str,
    expect_state_hash: str,
    kind: EventKind,
    fields: Mapping[str, Any],
    timestamp: Optional[str] = None,
) -> RecordResult:
    root_path = Path(root).resolve()
    with _lock(root_path):
        snapshot = Snapshot.capture(root_path)
        directive = engine.decide(snapshot)
        if directive.id != directive_id:
            if snapshot.state_hash != expect_state_hash:
                raise StaleDirective(
                    "the workspace moved on since the directive was issued "
                    f"(expected state {expect_state_hash}, found {snapshot.state_hash}) and the "
                    f"current move is now {directive.kind.value} ({directive.id}); "
                    "ask the engine for a fresh directive"
                )
            raise UnknownDirective(
                f"directive {directive_id} is not the engine's current move "
                f"({directive.id}: {directive.kind.value})"
            )
        _validate(directive, kind, fields)

        events = _events_for(snapshot, directive, kind, fields, timestamp or _now())
        _append(root_path, events)
        after = Snapshot.capture(root_path)
        _write_state_doc(root_path, after, directive)
        final = Snapshot.capture(root_path)
        return RecordResult(events=tuple(events), state_hash=final.state_hash,
                            directive=directive)


def initialize(root: "os.PathLike[str] | str") -> None:
    """Create the internal directories and the audit header (idempotent)."""

    root_path = Path(root).resolve()
    (root_path / INTERNAL_DIR).mkdir(parents=True, exist_ok=True)
    audit_path = root_path / artifacts.AUDIT_PATH
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    if not audit_path.exists():
        audit_path.write_text(audit.HEADER, encoding="utf-8")
        _reindex(root_path)


def rebuild(root: "os.PathLike[str] | str") -> int:
    """Regenerate audit.md and aidlc-state.md from the ledger.

    This is the documented recovery for a corrupted or overwritten audit log:
    the ledger is the source of truth, the Markdown is a projection of it.
    """

    root_path = Path(root).resolve()
    with _lock(root_path):
        snapshot = Snapshot.capture(root_path)
        body = [audit.HEADER]
        for raw in snapshot.ledger:
            body.append(audit.render(_event_from_dict(raw)))
        audit_path = root_path / artifacts.AUDIT_PATH
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text("".join(body), encoding="utf-8")
        _reindex(root_path)
        _write_state_doc(root_path, Snapshot.capture(root_path), None)
        return len(snapshot.ledger)


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def _validate(directive: Directive, kind: EventKind, fields: Mapping[str, Any]) -> None:
    if kind not in directive.settles:
        allowed = ", ".join(e.value for e in directive.settles) or "(none)"
        raise InvalidEvent(
            f"{directive.kind.value} is not settled by a '{kind.value}' event; "
            f"allowed: {allowed}"
        )
    missing = [f for f in required_event_fields(kind) if not _present(fields, f)]
    if missing:
        raise InvalidEvent(
            f"'{kind.value}' requires field(s): {', '.join(missing)}"
        )


def _present(fields: Mapping[str, Any], name: str) -> bool:
    value = fields.get(name)
    if isinstance(value, bool):
        return True
    return value not in (None, "", [], {})


# --------------------------------------------------------------------------
# event construction
# --------------------------------------------------------------------------

def _events_for(
    snapshot: Snapshot,
    directive: Directive,
    kind: EventKind,
    fields: Mapping[str, Any],
    timestamp: str,
) -> List[AuditEvent]:
    merged: Dict[str, Any] = dict(fields)
    if directive.part:
        merged["part"] = directive.part
    if directive.depth and "depth" not in merged:
        merged["depth"] = directive.depth.value

    events: List[AuditEvent] = []
    opens_stage = (
        kind is EventKind.STAGE_COMPLETED
        and directive.stage is not None
        and snapshot.status(directive.stage, directive.unit) is StageStatus.PENDING
    )
    if opens_stage:
        events.append(AuditEvent(
            kind=EventKind.STAGE_STARTED,
            timestamp=timestamp,
            directive_id=directive.id,
            stage=directive.stage,
            unit=directive.unit,
            fields={"opened_by": directive.kind.value},
        ))

    events.append(AuditEvent(
        kind=kind,
        timestamp=timestamp,
        directive_id=directive.id,
        stage=directive.stage,
        unit=directive.unit,
        fields=merged,
    ))

    closure = _approval_closure(directive, kind, merged, timestamp)
    if closure is not None:
        events.append(closure)
    return events


def _approval_closure(
    directive: Directive,
    kind: EventKind,
    fields: Mapping[str, Any],
    timestamp: str,
) -> Optional[AuditEvent]:
    """An approving response to a final gate closes the stage.

    The directive itself declares this (``payload.on_approval.complete_stage``);
    the recorder only carries out what the engine specified.
    """

    if directive.kind is not DirectiveKind.AWAIT_APPROVAL or kind is not \
            EventKind.APPROVAL_RESPONSE:
        return None
    on_approval = directive.payload.get("on_approval", {})
    if not isinstance(on_approval, Mapping) or not on_approval.get("complete_stage"):
        return None
    decision = str(fields.get("decision", "")).lower()
    if decision not in ("approve", "approved", "continue", "yes"):
        return None
    return AuditEvent(
        kind=EventKind.STAGE_COMPLETED,
        timestamp=timestamp,
        directive_id=directive.id,
        stage=directive.stage,
        unit=directive.unit,
        fields={"closed_by": "approval"},
    )


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------

def _append(root: Path, events: List[AuditEvent]) -> None:
    ledger_path = root / LEDGER_PATH
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path = root / artifacts.AUDIT_PATH
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    if not audit_path.exists():
        audit_path.write_text(audit.HEADER, encoding="utf-8")

    with ledger_path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
    with audit_path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(audit.render(event))
    _reindex(root)


def _reindex(root: Path) -> None:
    """Record the audit file's length and prefix hash so tampering is visible."""

    import hashlib

    audit_path = root / artifacts.AUDIT_PATH
    data = audit_path.read_bytes() if audit_path.exists() else b""
    index = {
        "length": len(data),
        "prefix_sha256": hashlib.sha256(data).hexdigest(),
    }
    index_path = root / AUDIT_INDEX_PATH
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _write_state_doc(root: Path, snapshot: Snapshot, directive: Optional[Directive]) -> None:
    current = None
    if directive is not None:
        current = f"{directive.kind.value} {directive.stage or ''}".strip()
    path = root / artifacts.STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(statedoc.render(snapshot, current), encoding="utf-8")


def _event_from_dict(raw: Mapping[str, Any]) -> AuditEvent:
    return AuditEvent(
        kind=EventKind(str(raw.get("kind"))),
        timestamp=str(raw.get("timestamp", "")),
        directive_id=str(raw.get("directive_id", "")),
        stage=raw.get("stage"),
        unit=raw.get("unit"),
        fields=raw.get("fields", {}),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _lock(root: Path) -> Iterator[None]:
    path = root / LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise ConcurrentWrite(
                f"another writer holds {LOCK_PATH}; remove it only if no recorder is running"
            ) from exc
        raise
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        yield
    finally:
        try:
            path.unlink()
        except OSError:  # pragma: no cover - best effort
            pass
