"""Check semantics.

Ported from the source project's error-handling rules: the same severity ladder
(critical / high / medium / low), the same "Do Not Proceed" conditions, and the
same recovery procedures — expressed as executable checks over a snapshot.

A check never writes and never raises: it returns a ``CheckResult``.

Standard library only.
"""

from __future__ import annotations

import hashlib
import re
from typing import Callable, List, Mapping, Optional, Sequence, Set, Tuple

from . import artifacts, stages
from .model import CheckResult, CheckStatus, DirectiveKind, EventKind, Gate, Severity, StageStatus
from .state import Snapshot

BLANK_ANSWER = re.compile(r"^\s*\[Answer\]:\s*$", re.MULTILINE)
UNCHECKED_BOX = re.compile(r"^\s*[-*]?\s*\[ \]", re.MULTILINE)

CheckFn = Callable[[Snapshot], List[CheckResult]]


def _ok(check_id: str, severity: Severity, detail: str = "") -> CheckResult:
    return CheckResult(id=check_id, status=CheckStatus.PASS, severity=severity, detail=detail)


def _na(check_id: str, severity: Severity, detail: str = "") -> CheckResult:
    return CheckResult(id=check_id, status=CheckStatus.NA, severity=severity, detail=detail)


def _fail(
    check_id: str,
    severity: Severity,
    detail: str,
    recovery: str,
    stage: Optional[str] = None,
    unit: Optional[str] = None,
    remediation_kind: str = DirectiveKind.REMEDIATE.value,
) -> CheckResult:
    return CheckResult(
        id=check_id,
        status=CheckStatus.FAIL,
        severity=severity,
        detail=detail,
        stage=stage,
        unit=unit,
        recovery=recovery,
        remediation_kind=remediation_kind,
    )


# --------------------------------------------------------------------------
# state consistency
# --------------------------------------------------------------------------

def check_state_present(snapshot: Snapshot) -> List[CheckResult]:
    if not snapshot.completed(stages.WORKSPACE_DETECTION):
        return [_na("state.present", Severity.CRITICAL, "workspace detection not complete yet")]
    if snapshot.exists(artifacts.STATE_PATH):
        return [_ok("state.present", Severity.CRITICAL)]
    return [_fail(
        "state.present", Severity.CRITICAL,
        f"{artifacts.STATE_PATH} is missing although workspace detection completed",
        "Rebuild aidlc-state.md from the existing artifacts and the ledger, then continue.",
        stage=stages.WORKSPACE_DETECTION,
    )]


def check_state_parseable(snapshot: Snapshot) -> List[CheckResult]:
    if not snapshot.exists(artifacts.STATE_PATH):
        return [_na("state.parseable", Severity.CRITICAL)]
    text = snapshot.text(artifacts.STATE_PATH)
    if text.strip() and "# AI-DLC State" in text:
        return [_ok("state.parseable", Severity.CRITICAL)]
    return [_fail(
        "state.parseable", Severity.CRITICAL,
        "aidlc-state.md is empty or does not carry the expected heading",
        "Back up the file as aidlc-state.md.backup, regenerate it from the ledger, and resume.",
    )]


def check_single_current(snapshot: Snapshot) -> List[CheckResult]:
    in_progress: List[str] = []
    for stage in stages.STAGES:
        units: Sequence[Optional[str]] = snapshot.units() if stage.per_unit else (None,)
        for unit in units:
            if snapshot.status(stage.id, unit) is StageStatus.IN_PROGRESS:
                in_progress.append(f"{stage.id}[{unit}]" if unit else stage.id)
    if len(in_progress) <= 1:
        return [_ok("state.single_current", Severity.HIGH)]
    return [_fail(
        "state.single_current", Severity.HIGH,
        f"multiple stages are marked current: {', '.join(in_progress)}",
        "Review the artifacts to determine actual progress, then correct the state so exactly "
        "one stage is current.",
    )]


def check_artifacts(snapshot: Snapshot) -> List[CheckResult]:
    """Completed stages must have left their required artifacts behind."""

    results: List[CheckResult] = []
    missing_any = False
    empty_any = False
    for stage in stages.STAGES:
        units: Sequence[Optional[str]] = snapshot.units() if stage.per_unit else (None,)
        for unit in units:
            if not snapshot.completed(stage.id, unit):
                continue
            for artifact_id in stage.produces:
                if artifact_id in artifacts.RECORDER_OWNED:
                    continue
                artifact = artifacts.get(artifact_id)
                if not artifact.required:
                    continue
                path = artifact.resolve(unit)
                if not snapshot.exists(path):
                    missing_any = True
                    results.append(_fail(
                        "artifacts.present", Severity.CRITICAL,
                        f"{stage.id} is complete but {path} is missing",
                        f"Return to {stage.title} and regenerate the missing artifact "
                        "(or reset the stage to incomplete).",
                        stage=stage.id, unit=unit,
                    ))
                elif not snapshot.non_empty(path):
                    empty_any = True
                    results.append(_fail(
                        "artifacts.non_empty", Severity.HIGH,
                        f"{path} exists but is empty",
                        f"Back up the empty file and regenerate it from {stage.title}.",
                        stage=stage.id, unit=unit,
                    ))
    if not missing_any:
        results.append(_ok("artifacts.present", Severity.CRITICAL))
    if not empty_any:
        results.append(_ok("artifacts.non_empty", Severity.HIGH))
    return results


def check_state_matches_artifacts(snapshot: Snapshot) -> List[CheckResult]:
    """Artifacts on disk for a stage the ledger says never ran.

    Only stages that a *later* stage has already overtaken count: while a stage
    is being executed its artifacts legitimately exist before its completion
    event is recorded.
    """

    stale: List[str] = []
    for stage in stages.STAGES:
        if not stage.produces:
            continue
        units: Sequence[Optional[str]] = snapshot.units() if stage.per_unit else (None,)
        for unit in units:
            if snapshot.status(stage.id, unit) is not StageStatus.PENDING:
                continue
            if not _overtaken(snapshot, stage.id, unit):
                continue
            required = [
                a for a in stage.produces
                if artifacts.get(a).required and a not in artifacts.RECORDER_OWNED
            ]
            if required and all(snapshot.artifact_exists(a, unit) for a in required):
                stale.append(f"{stage.id}[{unit}]" if unit else stage.id)
    if not stale:
        return [_ok("state.matches_artifacts", Severity.HIGH)]
    return [_fail(
        "state.matches_artifacts", Severity.HIGH,
        f"artifacts exist for stages the state calls pending: {', '.join(stale)}",
        "Verify the artifacts are complete and valid, then record the stage as completed "
        "(or archive the artifacts and re-run the stage).",
        stage=stale[0].split("[")[0],
    )]


def _overtaken(snapshot: Snapshot, stage_id: str, unit: Optional[str]) -> bool:
    """True when work that comes after this (stage, unit) is already settled.

    For a per-unit stage only the same unit's later stages count: units advance
    independently, so unit B being untouched while unit A finishes is normal.
    """

    position = stages.index(stage_id)
    for later in stages.STAGES[position + 1:]:
        if later.per_unit:
            targets: Sequence[Optional[str]] = (unit,) if unit else snapshot.units()
        else:
            targets = (None,)
        if any(snapshot.settled(later.id, target) for target in targets):
            return True
    return False


# --------------------------------------------------------------------------
# gates
# --------------------------------------------------------------------------

def check_questions_answered(snapshot: Snapshot) -> List[CheckResult]:
    results: List[CheckResult] = []
    failed = False
    for event in snapshot.events(EventKind.ANSWERS_RECEIVED):
        path = str(event.get("fields", {}).get("path", ""))
        if not path or not snapshot.exists(path):
            continue
        if BLANK_ANSWER.search(snapshot.text(path)):
            failed = True
            results.append(_fail(
                "questions.answered", Severity.HIGH,
                f"{path} still has blank [Answer]: tags after answers were recorded",
                "Highlight the unanswered questions, provide examples, and wait for answers. "
                "Do not proceed until every required question is answered.",
                stage=event.get("stage"), unit=event.get("unit"),
            ))
    if not failed:
        results.append(_ok("questions.answered", Severity.HIGH))
    return results


def check_no_open_ambiguity(snapshot: Snapshot) -> List[CheckResult]:
    open_items = snapshot.open_ambiguities()
    if not open_items:
        return [_ok("questions.unambiguous", Severity.HIGH)]
    first = open_items[0]
    return [_fail(
        "questions.unambiguous", Severity.HIGH,
        str(first.get("fields", {}).get("description", "unresolved ambiguity")),
        "Create follow-up questions naming each ambiguity and wait for the answers. "
        "Do not move forward until all ambiguities are resolved.",
        stage=first.get("stage"), unit=first.get("unit"),
    )]


def check_plan_checkboxes(snapshot: Snapshot) -> List[CheckResult]:
    results: List[CheckResult] = []
    failed = False
    plan_ids = {a.id for a in artifacts.all_artifacts() if a.id.startswith("plans.")}
    for stage in stages.STAGES:
        units: Sequence[Optional[str]] = snapshot.units() if stage.per_unit else (None,)
        for unit in units:
            if not snapshot.completed(stage.id, unit):
                continue
            for artifact_id in stage.produces:
                if artifact_id not in plan_ids:
                    continue
                path = artifacts.resolve(artifact_id, unit)
                if snapshot.exists(path) and UNCHECKED_BOX.search(snapshot.text(path)):
                    failed = True
                    results.append(_fail(
                        "plan.checkboxes_complete", Severity.HIGH,
                        f"{path} still has unchecked steps although {stage.id} is complete",
                        "Resume from the first unchecked step; mark each step [x] in the same "
                        "interaction in which the work is completed.",
                        stage=stage.id, unit=unit,
                    ))
    if not failed:
        results.append(_ok("plan.checkboxes_complete", Severity.HIGH))
    return results


def check_approvals(snapshot: Snapshot) -> List[CheckResult]:
    results: List[CheckResult] = []
    failed = False
    for stage in stages.STAGES:
        if stage.gate in (Gate.NONE, Gate.AUTO_PROCEED):
            continue
        units: Sequence[Optional[str]] = snapshot.units() if stage.per_unit else (None,)
        for unit in units:
            if not snapshot.completed(stage.id, unit):
                continue
            gate = snapshot.gate(stage.id, unit)
            if not gate.approved:
                failed = True
                results.append(_fail(
                    "approval.recorded", Severity.CRITICAL,
                    f"{stage.id} is complete without a recorded approval response",
                    "Present the stage completion message and wait for explicit approval; "
                    "log the prompt before asking and the verbatim response after.",
                    stage=stage.id, unit=unit,
                ))
    if not failed:
        results.append(_ok("approval.recorded", Severity.CRITICAL))
    return results


# --------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------

def check_units_acyclic(snapshot: Snapshot) -> List[CheckResult]:
    deps = snapshot.unit_dependencies()
    if not deps:
        return [_na("units.acyclic", Severity.HIGH)]
    cycle = _find_cycle(deps)
    if cycle is None:
        return [_ok("units.acyclic", Severity.HIGH)]
    return [_fail(
        "units.acyclic", Severity.HIGH,
        "circular unit dependency: " + " -> ".join(cycle),
        "Revise the unit boundaries to break the cycle, then update unit-of-work-dependency.md.",
        stage=stages.UNITS_GENERATION,
    )]


def check_unit_deps_satisfied(snapshot: Snapshot) -> List[CheckResult]:
    deps = snapshot.unit_dependencies()
    if not deps:
        return [_na("units.deps_satisfied", Severity.HIGH)]
    results: List[CheckResult] = []
    failed = False
    for unit in snapshot.units():
        if not snapshot.completed(stages.CODE_GENERATION, unit):
            continue
        for dependency in deps.get(unit, ()):
            if not snapshot.completed(stages.CODE_GENERATION, dependency):
                failed = True
                results.append(_fail(
                    "units.deps_satisfied", Severity.HIGH,
                    f"code generation completed for {unit} before its dependency {dependency}",
                    "Reorder the generation sequence to respect dependencies, or record the "
                    "stub-and-integrate workaround.",
                    stage=stages.CODE_GENERATION, unit=unit,
                ))
    if not failed:
        results.append(_ok("units.deps_satisfied", Severity.HIGH))
    return results


def _find_cycle(graph: Mapping[str, Sequence[str]]) -> Optional[List[str]]:
    visiting: Set[str] = set()
    done: Set[str] = set()
    path: List[str] = []

    def visit(node: str) -> Optional[List[str]]:
        if node in done:
            return None
        if node in visiting:
            start = path.index(node)
            return path[start:] + [node]
        visiting.add(node)
        path.append(node)
        for neighbour in graph.get(node, ()):
            found = visit(neighbour)
            if found:
                return found
        path.pop()
        visiting.discard(node)
        done.add(node)
        return None

    for node in sorted(graph):
        found = visit(node)
        if found:
            return found
    return None


# --------------------------------------------------------------------------
# extensions, audit, content
# --------------------------------------------------------------------------

def check_extensions_configured(snapshot: Snapshot) -> List[CheckResult]:
    if not snapshot.completed(stages.REQUIREMENTS_ANALYSIS):
        return [_na("extensions.configured", Severity.MEDIUM)]
    if snapshot.extensions():
        return [_ok("extensions.configured", Severity.MEDIUM)]
    return [_fail(
        "extensions.configured", Severity.MEDIUM,
        "no extension opt-in decisions were recorded during requirements analysis",
        "Record each extension's enablement under '## Extension Configuration' in the state "
        "file; default to enforced when no configuration exists.",
        stage=stages.REQUIREMENTS_ANALYSIS,
    )]


def check_extension_compliance(snapshot: Snapshot) -> List[CheckResult]:
    failing = [
        e for e in snapshot.events(EventKind.EXTENSION_COMPLIANCE)
        if str(e.get("fields", {}).get("status", "")).lower() == "non-compliant"
        and not e.get("fields", {}).get("resolved")
    ]
    if not failing:
        return [_ok("extensions.compliance", Severity.HIGH)]
    first = failing[0]
    return [_fail(
        "extensions.compliance", Severity.HIGH,
        f"extension {first.get('fields', {}).get('extension')} is non-compliant: "
        f"{first.get('fields', {}).get('summary')}",
        "Non-compliance with an applicable enabled extension rule is a blocking finding; "
        "resolve it before presenting stage completion.",
        stage=first.get("stage"), unit=first.get("unit"),
    )]


def check_initial_request_logged(snapshot: Snapshot) -> List[CheckResult]:
    if snapshot.initial_request_logged():
        return [_ok("audit.initial_request", Severity.CRITICAL)]
    return [_fail(
        "audit.initial_request", Severity.CRITICAL,
        "the user's raw initial request was never logged",
        "Log the complete raw user input in audit.md before doing anything else.",
        remediation_kind=DirectiveKind.RECORD_AUDIT.value,
    )]


def check_audit_append_only(snapshot: Snapshot) -> List[CheckResult]:
    index = snapshot.audit_index
    actual = snapshot.audit_actual
    if not index or not actual.get("exists"):
        return [_na("audit.append_only", Severity.CRITICAL)]
    recorded_length = int(index.get("length", 0))
    if int(actual.get("length", 0)) < recorded_length:
        return [_fail(
            "audit.append_only", Severity.CRITICAL,
            "audit.md shrank: it was overwritten rather than appended to",
            "Restore audit.md from the ledger (aidlc rebuild) — never overwrite the audit log.",
        )]
    if index.get("prefix_sha256") and index.get("prefix_sha256") != _prefix(snapshot,
                                                                            recorded_length):
        return [_fail(
            "audit.append_only", Severity.CRITICAL,
            "the existing prefix of audit.md changed: history was rewritten",
            "Restore audit.md from the ledger (aidlc rebuild) — the audit log is append-only.",
        )]
    return [_ok("audit.append_only", Severity.CRITICAL)]


def _prefix(snapshot: Snapshot, length: int) -> str:
    text = snapshot.text(artifacts.AUDIT_PATH)
    return hashlib.sha256(text.encode("utf-8")[:length]).hexdigest()


def check_content_validation(snapshot: Snapshot) -> List[CheckResult]:
    unresolved = [
        e for e in snapshot.events(EventKind.CONTENT_VALIDATION)
        if str(e.get("fields", {}).get("outcome", "")).lower() == "failed"
        and not e.get("fields", {}).get("fallback_used")
    ]
    if not unresolved:
        return [_ok("content.validated", Severity.MEDIUM)]
    first = unresolved[0]
    return [_fail(
        "content.validated", Severity.MEDIUM,
        f"content validation failed for {first.get('fields', {}).get('target')} "
        "and no fallback was recorded",
        "Switch to the text-based alternative, log the fallback, and continue — content "
        "validation failures must not block the workflow.",
        stage=first.get("stage"), unit=first.get("unit"),
    )]


ALL_CHECKS: Tuple[CheckFn, ...] = (
    check_initial_request_logged,
    check_audit_append_only,
    check_state_present,
    check_state_parseable,
    check_single_current,
    check_artifacts,
    check_state_matches_artifacts,
    check_approvals,
    check_questions_answered,
    check_no_open_ambiguity,
    check_plan_checkboxes,
    check_units_acyclic,
    check_unit_deps_satisfied,
    check_extension_compliance,
    check_extensions_configured,
    check_content_validation,
)


def run_all(snapshot: Snapshot) -> Tuple[CheckResult, ...]:
    results: List[CheckResult] = []
    for check in ALL_CHECKS:
        results.extend(check(snapshot))
    return tuple(results)


def blocking(results: Sequence[CheckResult]) -> Tuple[CheckResult, ...]:
    return tuple(r for r in results if r.blocking)


def advisories(results: Sequence[CheckResult]) -> Tuple[CheckResult, ...]:
    return tuple(
        r for r in results
        if r.status is CheckStatus.FAIL and r.severity in (Severity.MEDIUM, Severity.LOW)
    )
