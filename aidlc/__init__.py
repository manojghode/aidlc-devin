"""AI-DLC for Devin: a deterministic, dependency-free lifecycle engine.

The engine is authoritative over sequencing: :func:`aidlc.engine.step` returns
exactly one typed directive per turn, never writes, and never calls a model.
:mod:`aidlc.recorder` is the only writer.

Standard library only — no third-party imports anywhere in this package.
"""

from .model import (
    AidlcError,
    AuditEvent,
    CheckResult,
    Depth,
    Directive,
    DirectiveKind,
    EngineMutatedState,
    EventKind,
    Gate,
    InvalidEvent,
    Phase,
    Policy,
    Severity,
    Stage,
    StageStatus,
    StaleDirective,
    UnknownDirective,
)

__all__ = [
    "AidlcError",
    "AuditEvent",
    "CheckResult",
    "Depth",
    "Directive",
    "DirectiveKind",
    "EngineMutatedState",
    "EventKind",
    "Gate",
    "InvalidEvent",
    "Phase",
    "Policy",
    "Severity",
    "Stage",
    "StageStatus",
    "StaleDirective",
    "UnknownDirective",
]
__version__ = "0.1.0"
