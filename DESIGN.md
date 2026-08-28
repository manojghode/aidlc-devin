# AI-DLC for Devin — Design

A deterministic development-lifecycle engine for Devin.

The valuable content of the AI-DLC lifecycle — the stage set and its
requires/produces/consumes edges, the check semantics, the audit event taxonomy,
and the directive kinds implied by its gates — is preserved verbatim in meaning.
What is new here is *how the loop is driven*: conventionally a markdown rulebook
asks the model to sequence itself. Here a dependency-free Python engine owns
sequencing, and Devin executes one move at a time.

---

## 1. Architecture

```text
                 read-only                       append-only
  ┌───────────────────────────┐             ┌────────────────────────┐
  │  aidlc.engine             │             │  aidlc.recorder        │
  │  next_directive(snapshot) │             │  record(event)         │
  │  • pure function          │             │  • sole writer         │
  │  • never calls a model    │             │  • updates state md    │
  │  • one Directive / turn   │             │  • appends audit md    │
  └─────────────┬─────────────┘             └───────────┬────────────┘
                │ Directive (typed, JSON)               ▲ AuditEvent
                ▼                                       │
        ┌───────────────────────────────────────────────┴──────────┐
        │  Devin (the planner / executor)                          │
        │  decides HOW to execute the single move it is handed     │
        │  — never WHAT the next move is                           │
        └──────────────────────────────────────────────────────────┘
                                │
                                ▼
                    aidlc-docs/  +  workspace code
```

Two processes, one direction of flow. The engine reads the workspace and emits
one typed directive. Devin performs exactly that directive using its own tools.
Devin then reports what happened as an audit event through the recorder, which
is the only component allowed to write. The engine then runs again against the
new state. There is no other control flow.

### Why this satisfies "the engine is authoritative"

* `next_directive()` is a total function of the state snapshot. It has no
  advisory mode, no "suggested next stage", and no ranked list. It returns
  **one** `Directive`, or raises.
* Devin cannot skip ahead: the recorder refuses any event whose
  `expect_state_hash` does not match the current snapshot hash, and every
  recorded event changes the hash. One directive can therefore be settled by at
  most one recorded event — a second "move" in the same turn is mechanically
  rejected, not merely discouraged.
* Devin cannot substitute a different move: each directive carries a
  `directive_id` — a hash of the *move itself* (kind + stage + unit + part),
  deliberately not of the observation it came from, because an executor
  legitimately writes artifacts while carrying the move out. The recorder
  re-derives the current directive, requires the event to reference it, and
  rejects events whose `kind` is not in that directive's `settles` set. The
  separate `expect_state_hash` is the optimistic-concurrency version: it is what
  catches a *stale* turn, where the current move has changed underneath Devin.
* Judgement calls that the source leaves to the model (is this stage worth
  running? at what depth?) are not deleted — they are *scheduled*. The engine
  hands out an `ASSESS_CONDITIONAL` directive whose whole content is "assess
  stage X against these criteria and record the verdict". The verdict is data
  the engine then sequences on. Devin decides the *content* of the assessment;
  the engine decides *when an assessment is the move*.

### Read-only enforcement

`Engine.step()`:

1. captures a `Snapshot` (path → sha256 for everything under `aidlc-docs/`, plus
   a bounded workspace code fingerprint) and computes `state_hash`;
2. computes the directive from the snapshot alone — no I/O other than the reads
   already folded into the snapshot, no subprocesses, no sockets, no clock use
   in the decision path;
3. re-captures the snapshot and asserts `state_hash` is unchanged, raising
   `EngineMutatedState` otherwise.

The assertion is a real runtime invariant, not a comment: it fails loudly if
anyone ever adds a write to the decision path. `tests/test_invariants.py` also
drives the engine repeatedly against a live workspace and asserts that the file
listing (path + size) is byte-for-byte identical afterwards, and AST-scans the
package for any import that could reach a model or a shell (`socket`, `http`,
`urllib`, `subprocess`, `ssl`, `asyncio`, `ctypes`, ...).

### Dependency policy (hard constraint)

`aidlc/` imports only the CPython standard library — `argparse`, `dataclasses`,
`enum`, `hashlib`, `json`, `os`, `pathlib`, `re`, `sys`, `datetime`, `typing`.
No `pip install`, no lockfile, no vendored code, nothing to review in a
third-party risk process. `tests/` uses `unittest`, also stdlib. Enforced by
`tests/test_invariants.py`, which walks every `import` node in the package and
compares against `sys.stdlib_module_names`, and additionally fails if a
dependency manifest (`requirements.txt`, `uv.lock`, `Pipfile`, `poetry.lock`)
appears in the repository at all.

---

## 2. Stage set and edges (reused from the source)

Three phases, fourteen stages. `ALWAYS` stages always execute; `CONDITIONAL`
stages require a recorded assessment; `PLACEHOLDER` is terminal-optional.
`per-unit` stages repeat once per unit of work, each unit completed fully before
the next.

| # | Stage id | Phase | Policy | Card. | Requires | Gate |
|---|---|---|---|---|---|---|
| 1 | `workspace_detection` | inception | ALWAYS | once | — | auto-proceed |
| 2 | `reverse_engineering` | inception | CONDITIONAL (brownfield, artifacts absent/stale) | once | 1 | approval |
| 3 | `requirements_analysis` | inception | ALWAYS (adaptive depth) | once | 1, 2* | questions + approval |
| 4 | `user_stories` | inception | CONDITIONAL | once | 3 | plan + questions + approval |
| 5 | `workflow_planning` | inception | ALWAYS | once | 3, 4* | approval |
| 6 | `application_design` | inception | CONDITIONAL | once | 5 | approval |
| 7 | `units_generation` | inception | CONDITIONAL | once | 5, 6* | approval |
| 8 | `functional_design` | construction | CONDITIONAL | per-unit | 5, 7* | approval |
| 9 | `nfr_requirements` | construction | CONDITIONAL | per-unit | 8* | approval |
| 10 | `nfr_design` | construction | CONDITIONAL (only if 9 executed) | per-unit | 9 | approval |
| 11 | `infrastructure_design` | construction | CONDITIONAL | per-unit | 10* | approval |
| 12 | `code_generation` | construction | ALWAYS | per-unit | 5, 8*–11* | plan approval + completion approval |
| 13 | `build_and_test` | construction | ALWAYS | once | 12 for all units | approval |
| 14 | `operations` | operations | PLACEHOLDER | once | 13 | — |

`*` = soft edge: required only if that stage was assessed as included.

Edge semantics are taken directly from the source's flowchart
(`common/process-overview.md`): solid arrows are hard `requires`, dotted arrows
are conditional entries, and `code_generation -.->|Next Unit| functional_design`
is the per-unit loop back edge.

### produces / consumes

Every stage declares the artifacts it produces and the artifacts it consumes,
taken from `docs/GENERATED_DOCS_REFERENCE.md` and
`common/session-continuity.md` ("Smart Context Loading by Stage"). Examples:

```text
requirements_analysis
  consumes: re.architecture?, re.component_inventory?, re.technology_stack?
  produces: req.questions, req.requirements
units_generation
  consumes: req.requirements, stories.stories?, ad.components?
  produces: plans.unit_of_work_plan, ad.unit_of_work,
            ad.unit_of_work_dependency, ad.unit_of_work_story_map
code_generation (per unit)
  consumes: ad.unit_of_work_story_map?, fd.*?, nfr.*?, infra.*?
  produces: plans.code_generation_plan{unit}, code.summaries{unit}
```

`?` marks optional (conditional) inputs. The engine uses `produces` to know what
a stage must have left behind before it may be marked complete, and `consumes`
to build the `context_to_load` list carried on every `RUN_STAGE` directive — so
context loading is engine-driven, not remembered by the model.

Depth (`MINIMAL` / `STANDARD` / `COMPREHENSIVE`) is per the source's
`common/depth-levels.md`: it never changes *which* artifacts a stage produces,
only their detail. It rides on the directive so the executor knows the rigour
expected.

---

## 3. Check semantics (reused from the source)

`common/error-handling.md` defines four severities and a set of
"Do Not Proceed" conditions and recovery procedures. Those become executable
checks. Each check yields `PASS`, `FAIL`, or `NA`, has a severity, and — when it
fails — names the recovery procedure that becomes a `REMEDIATE` directive.

| Check id | Severity | Fails when | Recovery |
|---|---|---|---|
| `state.present` | CRITICAL | `aidlc-state.md` missing after workspace detection | recreate from artifacts |
| `state.parseable` | CRITICAL | state file unreadable / malformed | backup + rebuild |
| `state.single_current` | HIGH | more than one stage marked current | rebuild from artifacts |
| `state.matches_artifacts` | HIGH | stage complete but `produces` missing, or artifacts present but stage incomplete | re-execute stage / reconcile state |
| `artifacts.present` | CRITICAL | a required produced artifact is missing | re-execute producing stage |
| `artifacts.non_empty` | HIGH | artifact exists but is empty/whitespace | backup + regenerate |
| `questions.answered` | HIGH | any `[Answer]:` tag left blank in an open question file | present file, await answers |
| `questions.unambiguous` | HIGH | an ambiguity was detected and not resolved | follow-up questions |
| `plan.checkboxes_complete` | HIGH | stage plan has `[ ]` steps left | resume from first unchecked step |
| `approval.recorded` | CRITICAL | gated stage has no `approval_response` after its `approval_prompt` | await approval |
| `units.acyclic` | HIGH | unit dependency graph has a cycle | revise unit boundaries |
| `units.deps_satisfied` | HIGH | code generation ordered before a dependency unit | reorder / stub |
| `extensions.configured` | MEDIUM | enabled extensions not recorded in state after requirements analysis | record config |
| `extensions.compliance` | HIGH | an enabled, applicable extension rule is non-compliant | resolve before completion |
| `audit.initial_request` | CRITICAL | user's raw initial request never logged | log it |
| `audit.append_only` | CRITICAL | `audit.md` shrank or its prefix changed | restore from backup |
| `content.validated` | MEDIUM | mermaid/ASCII validation failure recorded and no fallback | use text fallback |

Blocking = severity `CRITICAL` or `HIGH`. A blocking failure always wins the
turn: the engine emits `REMEDIATE` before any progress directive. `MEDIUM` and
`LOW` failures are attached to the next directive as `advisories` and never
stall the loop — matching the source's "don't block on content validation
failures".

---

## 4. Audit event taxonomy (reused from the source)

The source mandates four record formats (interaction, error, recovery, change
request) and an append-only ISO-8601 log. Those become the typed event set the
recorder accepts. Every event carries `timestamp`, `stage`, `unit?`,
`directive_id`, and preserves **complete raw user input, never summarised**.

```text
interaction            user_input + ai_response + context
stage_started          stage entered
stage_completed        stage's produces are on disk and gate passed
stage_skipped          conditional stage assessed out (reason required)
stage_restarted        restart of current or prior stage (impact + backups)
assessment             conditional-inclusion verdict + depth + rationale
approval_prompt        gate presented (logged BEFORE asking, per the source)
approval_response      user's verbatim reply + approved|changes_requested
questions_published    question file written, awaiting [Answer]: tags
answers_received       answers parsed, verbatim
ambiguity_detected     vague/contradictory answer found
ambiguity_resolved     follow-up answered
error                  type/description/cause/resolution/impact
recovery               issue/steps/outcome/artifacts_affected
change_request         request/current_state/impact/confirmation/action
change_confirmed       explicit user confirmation of impact
extension_decision     extension opted in/out at requirements analysis
extension_skipped      disabled extension skipped at a stage (source requires
                       this be logged)
extension_compliance   per-rule compliant/non-compliant/N-A summary
content_validation     validation failure + fallback used
human_task             AI cannot perform (credentials, network) — escalated
pause / resume         session continuity boundaries
workflow_completed     terminal
```

`audit.md` is only ever appended to (`open(..., "a")`); the `audit.append_only`
check hashes the previous prefix so an accidental overwrite — the failure mode
the source warns about twice in capitals — is detected on the next turn.

---

## 5. Directive kinds

Exactly one of these is emitted per turn. Each carries the state hash it was
computed from, the audit events that may settle it, and everything the executor
needs (rule text pointer, artifacts to produce, context to load, depth, unit).

| Kind | Meaning | Settled by |
|---|---|---|
| `RECORD_AUDIT` | a mandatory log entry is missing (e.g. the raw initial request) | `interaction` |
| `RESUME_SESSION` | existing project detected; present welcome-back and load the stage-appropriate artifact set | `resume` |
| `ASSESS_CONDITIONAL` | assess one conditional stage against its criteria; produce include/skip + depth + rationale | `assessment` |
| `RUN_STAGE` | execute one stage (or one *part* of a two-part stage) for one unit | `stage_completed`, `error` |
| `ASK_QUESTIONS` | publish a question file with `[Answer]:` tags | `questions_published` |
| `AWAIT_ANSWERS` | questions are open; present the file and stop | `answers_received`, `ambiguity_detected` |
| `AWAIT_APPROVAL` | present the stage completion message and stop for explicit approval | `approval_response` |
| `SKIP_STAGE` | record a skip with rationale and impact | `stage_skipped` |
| `REMEDIATE` | a blocking check failed; run the named recovery procedure | `recovery`, `error` |
| `CONFIRM_CHANGE` | a mid-workflow change was requested; assess impact and get explicit confirmation | `change_confirmed`, `change_request` |
| `ESCALATE_HUMAN` | a HUMAN TASK blocks progress | `human_task` |
| `HALT_COMPLETE` | lifecycle finished | `workflow_completed` |

Precedence inside a turn (first match wins — this *is* the sequencer):

```text
1. blocking check failure                → REMEDIATE
2. unconfirmed change request            → CONFIRM_CHANGE
3. open human task                       → ESCALATE_HUMAN
4. mandatory audit entry missing         → RECORD_AUDIT
5. resumable project, not yet resumed    → RESUME_SESSION
6. open question file with blank answers → AWAIT_ANSWERS
7. gate presented, approval outstanding  → AWAIT_APPROVAL
8. next stage is conditional, unassessed → ASSESS_CONDITIONAL
9. next stage assessed out               → SKIP_STAGE
10. next stage needs its question file   → ASK_QUESTIONS
11. otherwise                            → RUN_STAGE
12. no stages left                       → HALT_COMPLETE
```

---

## 6. How the loop is driven in Devin

This is the part that is not in the source. One Devin turn = one directive.

```text
   ┌─> aidlc next --json          (engine; read-only; one directive)
   │        │
   │        ├─ RUN_STAGE        → task_update in_progress; read `context_to_load`;
   │        │                     write `produces` with the file tools
   │        ├─ ASK_QUESTIONS    → write the question file, then message_user with
   │        │                     content_type="user_question"
   │        ├─ AWAIT_ANSWERS    → message_user(block_on_user=true)
   │        ├─ AWAIT_APPROVAL   → message_user(block_on_user=true), 2 options:
   │        │                     "Request Changes" / "Continue to Next Stage"
   │        ├─ ASSESS_CONDITIONAL → reason over the criteria in the payload
   │        ├─ REMEDIATE        → run the named recovery procedure
   │        ├─ ESCALATE_HUMAN   → message_user(block_on_user=true) / request_secret
   │        └─ HALT_COMPLETE    → git_create_pr, then final message_user
   │        │
   │        ▼
   └── aidlc record <event> --directive <id> --expect-state-hash <hash> ...
```

Concrete Devin bindings, chosen deliberately:

* **Task list mirrors the stage graph.** On the first `RUN_STAGE`, Devin creates
  one task per planned stage (`aidlc status` prints the projected plan in order) and
  flips exactly one to `in_progress` per turn. The user sees the lifecycle, not
  a wall of prose.
* **Gates use `message_user(block_on_user=true)`.** The source's "DO NOT PROCEED
  until user confirms" maps exactly onto Devin's blocking message. The two-option
  completion message becomes `content_type="user_question"` with the source's
  two options — no emergent third option, which the source explicitly forbids.
* **Questions stay in files.** The source requires multiple-choice questions in
  `.md` files with `[Answer]:` tags, not inline chat. Devin writes the file,
  attaches it, and links it with a `<ref_file>` citation; answers are read back
  from the file, so the artifact and the conversation cannot diverge.
* **Code generation ends in a PR.** `code_generation` for the last unit and
  `build_and_test` are the natural PR boundary: `fetch_pr_template` →
  `git_create_pr`. The audit trail and `aidlc-docs/` ship in the PR, which is
  what makes the lifecycle reviewable by a human.
* **`build_and_test` may hand off to the testing agent.** If the unit has a UI,
  the directive's `payload.verification` names it, and Devin hands off with
  `testing_agent(...)` instead of hand-driving a browser.
* **Session continuity is free.** Devin's long-horizon summarisation loses
  context; the engine does not. `RESUME_SESSION` reconstructs exactly the
  artifact set the source's `session-continuity.md` prescribes for the current
  stage, so a resumed session starts from files, not from memory.
* **Interrupts are events, not detours.** A mid-flight user message becomes an
  `interaction` (and, if it asks for a change, a `change_request`). The engine
  then re-derives the next move, so the workflow bends where the source says it
  should (`common/workflow-changes.md`) without the planner improvising.

### Turn contract

1. Devin must call `aidlc next` at the start of every turn, before anything else.
2. Devin must execute the returned directive and nothing else.
3. Devin must settle it with exactly one `aidlc record`, passing the directive id
   and the state hash from the directive. A stale hash means the world moved:
   Devin re-runs `aidlc next` and starts a fresh turn.
4. Devin never edits `aidlc-state.md` or `audit.md` by hand. The recorder owns
   both.

`.agents/skills/aidlc/SKILL.md` states this contract in the form Devin loads
automatically, so any session in a repo carrying the skill drives the loop the
same way.
