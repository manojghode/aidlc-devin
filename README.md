# AI-DLC for Devin

A deterministic development-lifecycle engine for Devin.

The AI-DLC lifecycle itself — the stage set and its requires/produces/consumes
edges, the check semantics, the audit event taxonomy, the gate/directive kinds —
is prior art, usually expressed as a Markdown rulebook that asks the model to
sequence itself. All of that content is preserved here. What is different is who
drives the loop: a dependency-free Python engine owns sequencing, and Devin
executes one move at a time.

```text
aidlc next   ──> exactly one typed Directive   (read-only, never calls a model)
   Devin executes that single move with its own tools
aidlc record ──> exactly one AuditEvent        (sole writer, append-only)
```

## Three properties the engine guarantees

1. **Authoritative sequencing.** `engine.step()` returns one `Directive` — not a
   list, not a recommendation. The planner decides *how* to execute the move it
   is handed, never *what* comes next. Judgement calls the source leaves to the
   model are not deleted, they are scheduled: the engine emits
   `ASSESS_CONDITIONAL` and sequences on the recorded verdict.
2. **Strictly read-only.** The state hash is captured before and after every
   decision and asserted unchanged (`EngineMutatedState` otherwise). Only
   `aidlc.recorder` writes, guarded by an expected state hash and an exclusive
   lock.
3. **Dependency-free.** The package imports the CPython standard library and
   nothing else — no lockfile, no vendored code, nothing for a third-party risk
   review to assess. A test enforces this by AST-scanning every import against
   `sys.stdlib_module_names`.

## Usage

```bash
python3 -m aidlc --root /path/to/workspace init      # create the ledger
python3 -m aidlc --root /path/to/workspace next      # the one move for this turn
python3 -m aidlc --root /path/to/workspace record \
    --directive-id <id> --state-hash <hash> \
    --kind interaction \
    --fields-json '{"user_input":"...","ai_response":"...","context":"initial request"}'
python3 -m aidlc --root /path/to/workspace status    # plan projection + checks
python3 -m aidlc --root /path/to/workspace rebuild   # regenerate docs from the ledger
python3 -m aidlc --root /path/to/workspace validate  # stage graph self-check
```

Everything is JSON on stdout, so an executor needs no client library.

## Layout

```text
aidlc/model.py      frozen value types: Directive, AuditEvent, CheckResult, enums
aidlc/stages.py     the source's 14 stages with their requires/produces/consumes edges
aidlc/artifacts.py  the source's aidlc-docs/ artifact paths
aidlc/state.py      Snapshot: the observation the engine decides from
aidlc/checks.py     the source's check semantics and severity ladder
aidlc/engine.py     sequencing — one directive per turn, read-only
aidlc/recorder.py   the only writer: ledger append, audit append, state projection
aidlc/audit.py      audit.md rendering (append-only)
aidlc/statedoc.py   aidlc-state.md rendering (a projection, never hand-edited)
aidlc/cli.py        python3 -m aidlc
.agents/skills/aidlc/SKILL.md  the turn contract Devin loads automatically
DESIGN.md           the full design, including what was reused and what is new
```

State lives in `aidlc-docs/.aidlc/ledger.jsonl`, an append-only event log.
`aidlc-state.md` and `audit.md` are projections of it and can always be rebuilt.

## Tests

```bash
python3 -m unittest discover -s tests -t tests -v
```

No third-party test runner, no plugins. The suite covers the three properties
above plus the sequencing rules, the recorder's rejection paths, the check
semantics, and the audit/directive taxonomies.
