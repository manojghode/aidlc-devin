"""Core value types for the AI-DLC engine.

Everything here is a frozen dataclass or an enum: the engine's decision path is
a pure function over these values, so they must be hashable and immutable.

Standard library only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


class Phase(str, Enum):
    INCEPTION = "inception"
    CONSTRUCTION = "construction"
    OPERATIONS = "operations"


class Policy(str, Enum):
    """Whether a stage runs unconditionally, on assessment, or not yet at all."""

    ALWAYS = "always"
    CONDITIONAL = "conditional"
    PLACEHOLDER = "placeholder"


class Cardinality(str, Enum):
    ONCE = "once"
    PER_UNIT = "per_unit"


class Gate(str, Enum):
    """What must happen before a stage is allowed to be marked complete."""

    NONE = "none"
    AUTO_PROCEED = "auto_proceed"
    APPROVAL = "approval"
    QUESTIONS_THEN_APPROVAL = "questions_then_approval"
    PLAN_THEN_APPROVAL = "plan_then_approval"


class Depth(str, Enum):
    MINIMAL = "minimal"
    STANDARD = "standard"
    COMPREHENSIVE = "comprehensive"


class StageStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class Severity(str, Enum):
    """Severity levels from the source's error-handling rules."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


BLOCKING_SEVERITIES = (Severity.CRITICAL, Severity.HIGH)


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NA = "na"


class DirectiveKind(str, Enum):
    RECORD_AUDIT = "RECORD_AUDIT"
    RESUME_SESSION = "RESUME_SESSION"
    ASSESS_CONDITIONAL = "ASSESS_CONDITIONAL"
    RUN_STAGE = "RUN_STAGE"
    ASK_QUESTIONS = "ASK_QUESTIONS"
    AWAIT_ANSWERS = "AWAIT_ANSWERS"
    AWAIT_APPROVAL = "AWAIT_APPROVAL"
    SKIP_STAGE = "SKIP_STAGE"
    REMEDIATE = "REMEDIATE"
    CONFIRM_CHANGE = "CONFIRM_CHANGE"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"
    HALT_COMPLETE = "HALT_COMPLETE"


class EventKind(str, Enum):
    """The audit event taxonomy, ported from the source's mandated log formats."""

    INTERACTION = "interaction"
    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    STAGE_SKIPPED = "stage_skipped"
    STAGE_RESTARTED = "stage_restarted"
    ASSESSMENT = "assessment"
    APPROVAL_PROMPT = "approval_prompt"
    APPROVAL_RESPONSE = "approval_response"
    QUESTIONS_PUBLISHED = "questions_published"
    ANSWERS_RECEIVED = "answers_received"
    AMBIGUITY_DETECTED = "ambiguity_detected"
    AMBIGUITY_RESOLVED = "ambiguity_resolved"
    ERROR = "error"
    RECOVERY = "recovery"
    CHANGE_REQUEST = "change_request"
    CHANGE_CONFIRMED = "change_confirmed"
    EXTENSION_DECISION = "extension_decision"
    EXTENSION_SKIPPED = "extension_skipped"
    EXTENSION_COMPLIANCE = "extension_compliance"
    CONTENT_VALIDATION = "content_validation"
    HUMAN_TASK = "human_task"
    PAUSE = "pause"
    RESUME = "resume"
    WORKFLOW_COMPLETED = "workflow_completed"


@dataclass(frozen=True)
class Artifact:
    """A documentation artifact the lifecycle produces or consumes.

    ``path`` is a template; ``{unit}`` is substituted for per-unit artifacts.
    """

    id: str
    path: str
    required: bool = True
    per_unit: bool = False
    is_dir: bool = False
    description: str = ""

    def resolve(self, unit: Optional[str] = None) -> str:
        if self.per_unit:
            if not unit:
                raise ValueError(f"artifact {self.id} requires a unit name")
            return self.path.format(unit=unit)
        return self.path


@dataclass(frozen=True)
class Stage:
    id: str
    title: str
    phase: Phase
    policy: Policy
    cardinality: Cardinality
    gate: Gate
    rule_ref: str
    requires: Tuple[str, ...] = ()
    soft_requires: Tuple[str, ...] = ()
    consumes: Tuple[str, ...] = ()
    optional_consumes: Tuple[str, ...] = ()
    produces: Tuple[str, ...] = ()
    optional_produces: Tuple[str, ...] = ()
    parts: Tuple[str, ...] = ()
    questions_artifact: Optional[str] = None
    include_criteria: Tuple[str, ...] = ()
    skip_criteria: Tuple[str, ...] = ()
    purpose: str = ""

    @property
    def per_unit(self) -> bool:
        return self.cardinality is Cardinality.PER_UNIT


@dataclass(frozen=True)
class CheckResult:
    id: str
    status: CheckStatus
    severity: Severity
    detail: str = ""
    stage: Optional[str] = None
    unit: Optional[str] = None
    recovery: str = ""
    remediation_kind: str = ""

    @property
    def blocking(self) -> bool:
        return self.status is CheckStatus.FAIL and self.severity in BLOCKING_SEVERITIES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status.value,
            "severity": self.severity.value,
            "detail": self.detail,
            "stage": self.stage,
            "unit": self.unit,
            "recovery": self.recovery,
        }


@dataclass(frozen=True)
class Directive:
    """The single typed move the engine hands to the executor for this turn."""

    kind: DirectiveKind
    state_hash: str
    reason: str
    stage: Optional[str] = None
    unit: Optional[str] = None
    part: Optional[str] = None
    depth: Optional[Depth] = None
    rule_ref: str = ""
    context_to_load: Tuple[str, ...] = ()
    produces: Tuple[str, ...] = ()
    settles: Tuple[EventKind, ...] = ()
    payload: Mapping[str, Any] = field(default_factory=dict)
    advisories: Tuple[CheckResult, ...] = ()

    @property
    def id(self) -> str:
        """Identity of the *move*, not of the observation it was computed from.

        Deliberately excludes ``state_hash``: an executor legitimately writes
        artifacts while carrying out the move it was handed, which changes the
        state hash. What must not change is which move the engine considers
        current — the recorder re-derives the directive and compares this id, so
        a settled event can never be attached to a different move.
        """

        material = json.dumps(
            {
                "kind": self.kind.value,
                "stage": self.stage,
                "unit": self.unit,
                "part": self.part,
            },
            sort_keys=True,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "directive_id": self.id,
            "kind": self.kind.value,
            "state_hash": self.state_hash,
            "reason": self.reason,
            "stage": self.stage,
            "unit": self.unit,
            "part": self.part,
            "depth": self.depth.value if self.depth else None,
            "rule_ref": self.rule_ref,
            "context_to_load": list(self.context_to_load),
            "produces": list(self.produces),
            "settles": [e.value for e in self.settles],
            "payload": _jsonable(self.payload),
            "advisories": [a.to_dict() for a in self.advisories],
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


@dataclass(frozen=True)
class AuditEvent:
    kind: EventKind
    timestamp: str
    directive_id: str
    stage: Optional[str] = None
    unit: Optional[str] = None
    fields: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "timestamp": self.timestamp,
            "directive_id": self.directive_id,
            "stage": self.stage,
            "unit": self.unit,
            "fields": _jsonable(self.fields),
        }


class AidlcError(Exception):
    """Base class for engine errors."""


class EngineMutatedState(AidlcError):
    """Raised when the read-only invariant of the decision path is violated."""


class StaleDirective(AidlcError):
    """Raised when an event is recorded against a state that has moved on."""


class UnknownDirective(AidlcError):
    """Raised when an event references a directive the engine did not emit."""


class InvalidEvent(AidlcError):
    """Raised when an event does not settle its directive or is missing fields."""


class ConcurrentWrite(AidlcError):
    """Raised when another writer holds the recorder lock."""


def required_event_fields(kind: EventKind) -> Sequence[str]:
    """Fields the source's log formats make mandatory for each event kind."""

    return _REQUIRED_FIELDS.get(kind, ())


_REQUIRED_FIELDS: Dict[EventKind, Tuple[str, ...]] = {
    EventKind.INTERACTION: ("user_input", "ai_response", "context"),
    EventKind.STAGE_SKIPPED: ("reason",),
    EventKind.ASSESSMENT: ("include", "rationale"),
    EventKind.APPROVAL_PROMPT: ("prompt",),
    EventKind.APPROVAL_RESPONSE: ("user_input", "decision"),
    EventKind.QUESTIONS_PUBLISHED: ("path",),
    EventKind.ANSWERS_RECEIVED: ("path", "user_input"),
    EventKind.AMBIGUITY_DETECTED: ("description",),
    EventKind.ERROR: ("error_type", "description", "cause", "impact"),
    EventKind.RECOVERY: ("issue", "steps", "outcome"),
    EventKind.CHANGE_REQUEST: ("request", "impact"),
    EventKind.CHANGE_CONFIRMED: ("request", "user_input", "action"),
    EventKind.EXTENSION_DECISION: ("extension", "enabled"),
    EventKind.EXTENSION_SKIPPED: ("extension", "reason"),
    EventKind.EXTENSION_COMPLIANCE: ("extension", "summary"),
    EventKind.CONTENT_VALIDATION: ("target", "outcome"),
    EventKind.HUMAN_TASK: ("description",),
    EventKind.STAGE_RESTARTED: ("reason", "impact"),
}
