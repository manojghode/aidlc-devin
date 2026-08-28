"""The sequencer.

``step()`` is authoritative: it emits exactly one typed directive per turn, it
is strictly read-only (it asserts the state hash is unchanged across the call),
and it never calls a model. The executor decides *how* to carry out the move it
is handed; it never decides *which* move comes next.

Standard library only.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from . import artifacts, checks, stages
from .model import (
    BLOCKING_SEVERITIES,
    CheckResult,
    Depth,
    Directive,
    DirectiveKind,
    EngineMutatedState,
    EventKind,
    Gate,
    Policy,
    Stage,
    StageStatus,
)
from .state import Snapshot

PART_EXECUTE = "execute"


def step(root: "os.PathLike[str] | str") -> Directive:
    """Capture the world, decide one move, and prove nothing was written."""

    before = Snapshot.capture(root)
    directive = decide(before)
    after = Snapshot.capture(root)
    if after.state_hash != before.state_hash:
        raise EngineMutatedState(
            "the engine's decision path modified the workspace: "
            f"{before.state_hash} -> {after.state_hash}"
        )
    return directive


def decide(snapshot: Snapshot) -> Directive:
    """Pure function: snapshot in, exactly one directive out."""

    results = checks.run_all(snapshot)
    advisories = checks.advisories(results)

    blocking = _highest_priority_blocker(results)
    if blocking is not None:
        return _remediation_directive(snapshot, blocking, advisories)

    for producer in (
        _change_request_move,
        _human_task_move,
        _resume_move,
        _answers_move,
        _approval_move,
        _progress_move,
    ):
        directive = producer(snapshot)
        if directive is not None:
            return _with_advisories(directive, advisories)

    return _with_advisories(
        Directive(
            kind=DirectiveKind.HALT_COMPLETE,
            state_hash=snapshot.state_hash,
            reason="every stage in the lifecycle is settled",
            settles=(EventKind.WORKFLOW_COMPLETED,),
        ),
        advisories,
    )


# --------------------------------------------------------------------------
# precedence rules
# --------------------------------------------------------------------------

def _highest_priority_blocker(results: Sequence[CheckResult]) -> Optional[CheckResult]:
    blockers = checks.blocking(results)
    if not blockers:
        return None
    for severity in BLOCKING_SEVERITIES:
        for result in blockers:
            if result.severity is severity:
                return result
    return blockers[0]


def _remediation_directive(
    snapshot: Snapshot,
    failure: CheckResult,
    advisories: Sequence[CheckResult],
) -> Directive:
    if failure.remediation_kind == DirectiveKind.RECORD_AUDIT.value:
        return _with_advisories(
            Directive(
                kind=DirectiveKind.RECORD_AUDIT,
                state_hash=snapshot.state_hash,
                reason=failure.detail,
                stage=failure.stage,
                unit=failure.unit,
                settles=(EventKind.INTERACTION,),
                payload={
                    "check": failure.to_dict(),
                    "instruction": failure.recovery,
                    "verbatim_required": True,
                },
            ),
            advisories,
        )
    return _with_advisories(
        Directive(
            kind=DirectiveKind.REMEDIATE,
            state_hash=snapshot.state_hash,
            reason=f"blocking check failed: {failure.id}",
            stage=failure.stage,
            unit=failure.unit,
            settles=(EventKind.RECOVERY, EventKind.ERROR),
            payload={
                "check": failure.to_dict(),
                "severity": failure.severity.value,
                "recovery": failure.recovery,
            },
        ),
        advisories,
    )


def _change_request_move(snapshot: Snapshot) -> Optional[Directive]:
    pending = snapshot.open_change_requests()
    if not pending:
        return None
    event = pending[0]
    fields = event.get("fields", {})
    request = str(fields.get("request", ""))
    return Directive(
        kind=DirectiveKind.CONFIRM_CHANGE,
        state_hash=snapshot.state_hash,
        reason="a mid-workflow change was requested and is not confirmed",
        stage=event.get("stage"),
        unit=event.get("unit"),
        settles=(EventKind.CHANGE_CONFIRMED, EventKind.CHANGE_REQUEST),
        payload={
            "request": request,
            "recorded_impact": fields.get("impact", ""),
            "affected_stages": _impact_of_change(snapshot, event),
            "instruction": (
                "Assess the full impact, present it, and obtain explicit confirmation before "
                "any destructive change. Archive affected artifacts as {artifact}.backup."
            ),
        },
    )


def _impact_of_change(snapshot: Snapshot, event: Mapping[str, Any]) -> List[str]:
    target = event.get("fields", {}).get("target_stage")
    if not target or target not in stages.BY_ID:
        return []
    start = stages.index(target)
    return [
        s.id for s in stages.STAGES[start:]
        if snapshot.status(s.id) is not StageStatus.PENDING or s.id == target
    ]


def _human_task_move(snapshot: Snapshot) -> Optional[Directive]:
    open_tasks = snapshot.open_human_tasks()
    if not open_tasks:
        return None
    event = open_tasks[0]
    return Directive(
        kind=DirectiveKind.ESCALATE_HUMAN,
        state_hash=snapshot.state_hash,
        reason="an open HUMAN TASK blocks progress",
        stage=event.get("stage"),
        unit=event.get("unit"),
        settles=(EventKind.HUMAN_TASK,),
        payload={
            "description": event.get("fields", {}).get("description", ""),
            "instruction": (
                "Surface the task to the user and wait for confirmation that it is done; "
                "record the human task again with resolved=true to close it."
            ),
        },
    )


def _resume_move(snapshot: Snapshot) -> Optional[Directive]:
    unresumed_external = snapshot.initialized() and not snapshot.ledger
    if not (snapshot.paused() or unresumed_external):
        return None
    target = _next_target(snapshot)
    stage_id = target[0].id if target else None
    unit = target[1] if target else None
    return Directive(
        kind=DirectiveKind.RESUME_SESSION,
        state_hash=snapshot.state_hash,
        reason=(
            "an existing AI-DLC project was detected and this session has not resumed it yet"
        ),
        stage=stage_id,
        unit=unit,
        context_to_load=_context_for(snapshot, target),
        settles=(EventKind.RESUME,),
        payload={
            "welcome_back": True,
            "current_stage": stage_id,
            "current_unit": unit,
            "options": [
                "Continue where you left off",
                "Review a previous stage",
            ],
            "instruction": (
                "Present the welcome-back summary from the state file, load the listed "
                "artifacts, and summarise what was loaded."
            ),
        },
    )


def _answers_move(snapshot: Snapshot) -> Optional[Directive]:
    open_questions = snapshot.open_questions()
    if not open_questions:
        return None
    event = open_questions[0]
    path = str(event.get("fields", {}).get("path", ""))
    return Directive(
        kind=DirectiveKind.AWAIT_ANSWERS,
        state_hash=snapshot.state_hash,
        reason=f"{path} is awaiting [Answer]: tags",
        stage=event.get("stage"),
        unit=event.get("unit"),
        settles=(EventKind.ANSWERS_RECEIVED, EventKind.AMBIGUITY_DETECTED),
        payload={
            "path": path,
            "blank_answers": bool(checks.BLANK_ANSWER.search(snapshot.text(path))),
            "instruction": (
                "Present the question file and stop. Record the user's answers verbatim; "
                "if any answer is vague or contradictory, record an ambiguity instead."
            ),
        },
    )


def _approval_move(snapshot: Snapshot) -> Optional[Directive]:
    """An approval prompt was logged and no response has been recorded yet."""

    for stage in stages.STAGES:
        units: Sequence[Optional[str]] = snapshot.units() if stage.per_unit else (None,)
        for unit in units:
            for part in (None,) + tuple(stage.parts):
                gate = snapshot.gate(stage.id, unit, part)
                if gate.prompt_pending:
                    return _await_approval(snapshot, stage, unit, part,
                                           reason="an approval prompt is outstanding")
    return None


def _progress_move(snapshot: Snapshot) -> Optional[Directive]:
    target = _next_target(snapshot)
    if target is None:
        return None
    stage, unit = target

    auto_skip = _auto_skip_reason(snapshot, stage, unit)
    if auto_skip:
        return _skip_directive(snapshot, stage, unit, auto_skip)

    if stage.policy is Policy.CONDITIONAL:
        assessment = snapshot.assessment(stage.id, unit)
        if assessment is None:
            return _assess_directive(snapshot, stage, unit)
        if not assessment.include:
            return _skip_directive(snapshot, stage, unit, assessment.rationale)

    return _stage_move(snapshot, stage, unit)


# --------------------------------------------------------------------------
# stage traversal
# --------------------------------------------------------------------------

def _next_target(snapshot: Snapshot) -> Optional[Tuple[Stage, Optional[str]]]:
    """The first stage/unit pair in lifecycle order that is not settled."""

    for stage in stages.STAGES:
        if stage.per_unit:
            continue
        if stage.id == stages.BUILD_AND_TEST:
            pending_unit = _first_unsettled_unit_stage(snapshot)
            if pending_unit is not None:
                return pending_unit
        if stage.policy is Policy.PLACEHOLDER:
            continue
        if not snapshot.settled(stage.id):
            return stage, None
    return None


def _first_unsettled_unit_stage(snapshot: Snapshot) -> Optional[Tuple[Stage, Optional[str]]]:
    """Per-unit loop: each unit is completed fully before the next one starts."""

    for unit in ordered_units(snapshot):
        for stage in stages.per_unit_stages():
            if not snapshot.settled(stage.id, unit):
                return stage, unit
    return None


def ordered_units(snapshot: Snapshot) -> Tuple[str, ...]:
    units = list(snapshot.units())
    deps = snapshot.unit_dependencies()
    if not deps:
        return tuple(units)
    ordered: List[str] = []
    seen: Set[str] = set()

    def visit(unit: str, trail: Tuple[str, ...] = ()) -> None:
        if unit in seen or unit in trail:
            return
        for dependency in deps.get(unit, ()):
            if dependency in units:
                visit(dependency, trail + (unit,))
        if unit not in seen:
            seen.add(unit)
            ordered.append(unit)

    for unit in units:
        visit(unit)
    return tuple(ordered)


def _auto_skip_reason(snapshot: Snapshot, stage: Stage, unit: Optional[str]) -> str:
    """Deterministic skips: a hard prerequisite was itself skipped."""

    for dependency in stage.requires:
        dep_unit = unit if stages.get(dependency).per_unit else None
        if snapshot.status(dependency, dep_unit) is StageStatus.SKIPPED:
            return (
                f"required stage '{stages.get(dependency).title}' was skipped, so "
                f"'{stage.title}' cannot and need not run"
            )
    return ""


def _stage_move(snapshot: Snapshot, stage: Stage, unit: Optional[str]) -> Directive:
    depth = snapshot.depth_for(stage.id, unit)

    if stage.questions_artifact:
        path = artifacts.resolve(stage.questions_artifact, unit)
        if not snapshot.questions_published_for(path):
            return Directive(
                kind=DirectiveKind.ASK_QUESTIONS,
                state_hash=snapshot.state_hash,
                reason=f"{stage.title} must publish its clarifying questions first",
                stage=stage.id,
                unit=unit,
                depth=depth,
                rule_ref=stage.rule_ref,
                context_to_load=_context_for(snapshot, (stage, unit)),
                produces=(path,),
                settles=(EventKind.QUESTIONS_PUBLISHED,),
                payload={
                    "path": path,
                    "answer_tag": "[Answer]:",
                    "instruction": (
                        "Write the questions to the file with lettered options (A, B, C, ...) "
                        "and a final 'Other' option, each followed by an empty [Answer]: tag. "
                        "Never ask these questions inline in chat. When in doubt, ask."
                    ),
                },
            )

    parts = tuple(stage.parts) or (PART_EXECUTE,)
    ungated = stage.gate in (Gate.NONE, Gate.AUTO_PROCEED)

    for part in parts:
        satisfied_by_questions = (
            part == stages.PART_PLANNING and stage.questions_artifact is not None
        )
        if not satisfied_by_questions and not snapshot.part_completed(stage.id, unit, part):
            single = len(parts) == 1
            return _run_stage(
                snapshot, stage, unit,
                part=None if (single and ungated) else part,
                depth=depth,
            )
        if part == stages.PART_PLANNING and stage.gate is Gate.PLAN_THEN_APPROVAL:
            if not snapshot.gate(stage.id, unit, part).approved:
                return _await_approval(
                    snapshot, stage, unit, part,
                    reason=f"{stage.title} plan must be approved before generation",
                )

    if not ungated and not snapshot.gate(stage.id, unit, None).approved:
        return _await_approval(
            snapshot, stage, unit, None,
            reason=f"{stage.title} is complete and awaiting explicit approval",
        )

    return _run_stage(snapshot, stage, unit, part=None, depth=depth,
                      reason=f"record completion of {stage.title}")


def _run_stage(
    snapshot: Snapshot,
    stage: Stage,
    unit: Optional[str],
    part: Optional[str],
    depth: Depth,
    reason: str = "",
) -> Directive:
    produced = tuple(
        artifacts.resolve(a, unit)
        for a in stage.produces + stage.optional_produces
        if a not in artifacts.RECORDER_OWNED
    )
    return Directive(
        kind=DirectiveKind.RUN_STAGE,
        state_hash=snapshot.state_hash,
        reason=reason or f"{stage.title} is the next stage in the lifecycle",
        stage=stage.id,
        unit=unit,
        part=part,
        depth=depth,
        rule_ref=stage.rule_ref,
        context_to_load=_context_for(snapshot, (stage, unit)),
        produces=produced,
        settles=(EventKind.STAGE_COMPLETED, EventKind.ERROR),
        payload={
            "purpose": stage.purpose,
            "phase": stage.phase.value,
            "required_artifacts": _required_paths(stage, unit),
            "optional_artifacts": [
                artifacts.resolve(a, unit)
                for a in stage.produces + stage.optional_produces
                if not artifacts.get(a).required and a not in artifacts.RECORDER_OWNED
            ],
            "extensions_enabled": dict(snapshot.extensions()),
            "content_validation_required": True,
            "instruction": (
                "Execute this stage only. Load the listed context first, validate content "
                "before writing any file, and write every required artifact."
            ),
        },
    )


def _await_approval(
    snapshot: Snapshot,
    stage: Stage,
    unit: Optional[str],
    part: Optional[str],
    reason: str,
) -> Directive:
    two_option = stage.id in stages.TWO_OPTION_STAGES
    return Directive(
        kind=DirectiveKind.AWAIT_APPROVAL,
        state_hash=snapshot.state_hash,
        reason=reason,
        stage=stage.id,
        unit=unit,
        part=part,
        rule_ref=stage.rule_ref,
        settles=(EventKind.APPROVAL_RESPONSE,),
        payload={
            "options": list(stages.COMPLETION_OPTIONS),
            "standardized_two_option": two_option,
            "artifacts_to_review": _required_paths(stage, unit),
            "on_approval": {"complete_stage": part is None},
            "instruction": (
                "Log the approval prompt before asking. Present exactly the listed options — "
                "no emergent third option — and stop until the user replies. Record the reply "
                "verbatim."
            ),
        },
    )


def _required_paths(stage: Stage, unit: Optional[str]) -> List[str]:
    return [
        artifacts.resolve(a, unit) for a in stage.produces
        if artifacts.get(a).required and a not in artifacts.RECORDER_OWNED
    ]


def _assess_directive(snapshot: Snapshot, stage: Stage, unit: Optional[str]) -> Directive:
    return Directive(
        kind=DirectiveKind.ASSESS_CONDITIONAL,
        state_hash=snapshot.state_hash,
        reason=f"{stage.title} is conditional and has not been assessed",
        stage=stage.id,
        unit=unit,
        rule_ref=stage.rule_ref,
        context_to_load=_context_for(snapshot, (stage, unit)),
        settles=(EventKind.ASSESSMENT,),
        payload={
            "include_criteria": list(stage.include_criteria),
            "skip_criteria": list(stage.skip_criteria),
            "depth_options": [d.value for d in Depth],
            "default_on_doubt": "include",
            "instruction": (
                "Assess this stage only. Record include=true/false, the depth, and a rationale "
                "citing the criteria. Depth changes rigour, never which artifacts are produced."
            ),
        },
    )


def _skip_directive(
    snapshot: Snapshot,
    stage: Stage,
    unit: Optional[str],
    reason: str,
) -> Directive:
    return Directive(
        kind=DirectiveKind.SKIP_STAGE,
        state_hash=snapshot.state_hash,
        reason=reason or f"{stage.title} was assessed out",
        stage=stage.id,
        unit=unit,
        settles=(EventKind.STAGE_SKIPPED,),
        payload={
            "rationale": reason,
            "downstream_effects": _downstream_of(stage),
            "instruction": (
                "Record the skip with its rationale; the state file and audit trail must show "
                "the stage as SKIPPED."
            ),
        },
    )


def _downstream_of(stage: Stage) -> List[str]:
    return [s.id for s in stages.STAGES if stage.id in s.requires + s.soft_requires]


def _context_for(
    snapshot: Snapshot,
    target: Optional[Tuple[Stage, Optional[str]]],
) -> Tuple[str, ...]:
    if target is None:
        return ()
    stage, unit = target
    paths: List[str] = []
    for artifact_id in stage.consumes:
        paths.extend(_consumed_paths(snapshot, artifact_id, unit))
    for artifact_id in stage.optional_consumes:
        paths.extend(
            p for p in _consumed_paths(snapshot, artifact_id, unit) if snapshot.exists(p)
        )
    for path in (artifacts.STATE_PATH,):
        if snapshot.exists(path):
            paths.insert(0, path)
    seen: Set[str] = set()
    ordered: List[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return tuple(ordered)


def _consumed_paths(snapshot: Snapshot, artifact_id: str, unit: Optional[str]) -> List[str]:
    """A once-only stage consuming a per-unit artifact consumes every unit's copy."""

    artifact = artifacts.get(artifact_id)
    if not artifact.per_unit:
        return [artifact.path]
    if unit:
        return [artifact.resolve(unit)]
    return [artifact.resolve(u) for u in ordered_units(snapshot)]


def _with_advisories(directive: Directive, advisories: Sequence[CheckResult]) -> Directive:
    if not advisories:
        return directive
    return Directive(
        kind=directive.kind,
        state_hash=directive.state_hash,
        reason=directive.reason,
        stage=directive.stage,
        unit=directive.unit,
        part=directive.part,
        depth=directive.depth,
        rule_ref=directive.rule_ref,
        context_to_load=directive.context_to_load,
        produces=directive.produces,
        settles=directive.settles,
        payload=directive.payload,
        advisories=tuple(advisories),
    )


def plan(snapshot: Snapshot) -> Tuple[Dict[str, object], ...]:
    """A read-only projection of the lifecycle, for mirroring into a task list."""

    rows: List[Dict[str, object]] = []
    for stage in stages.STAGES:
        if stage.policy is Policy.PLACEHOLDER:
            continue
        if stage.per_unit:
            for unit in ordered_units(snapshot):
                rows.append({
                    "stage": stage.id,
                    "title": f"{stage.title} ({unit})",
                    "unit": unit,
                    "status": snapshot.status(stage.id, unit).value,
                    "policy": stage.policy.value,
                })
        else:
            rows.append({
                "stage": stage.id,
                "title": stage.title,
                "unit": None,
                "status": snapshot.status(stage.id).value,
                "policy": stage.policy.value,
            })
    return tuple(rows)
