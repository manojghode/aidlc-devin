---
name: aidlc
description: Drive the AI-DLC deterministic development lifecycle. Use whenever a repository contains an aidlc-docs/ directory or the user asks to start, resume, or continue an AI-DLC workflow (requirements, user stories, units of work, functional/NFR design, code generation, build and test).
---

# AI-DLC turn loop

The engine owns sequencing. You do not choose the next step — you execute the
one move you are handed and report what happened. Every turn is:

```bash
python3 -m aidlc --root <workspace> next            # 1. get the one directive
# ... execute exactly that directive with your own tools ...
python3 -m aidlc --root <workspace> record \        # 2. settle it with one event
  --directive-id <directive_id> --state-hash <state_hash> \
  --kind <event kind from the directive's "settles"> --fields-json '{...}'
```

`next` is read-only and never calls a model. `record` is the only thing in the
system allowed to write `aidlc-docs/aidlc-state.md` and `aidlc-docs/audit.md`.

## Hard rules

1. Call `next` at the start of every turn, before anything else. Never infer the
   next stage yourself, never batch two moves into one turn, never reorder.
2. Execute only the directive you were handed. If you believe something else is
   more urgent, record it as an event (`change_request`, `error`, `human_task`)
   and call `next` again — the engine will re-sequence.
3. Settle each directive with exactly one `record` call, using its
   `directive_id` and `state_hash` verbatim.
4. `StaleDirective` means the world moved: discard your plan, call `next`, start
   a fresh turn. Never retry with the old hash.
5. Never hand-edit `aidlc-state.md` or `audit.md`. If they look wrong, run
   `python3 -m aidlc --root <workspace> rebuild`.
6. Log the user's initial request verbatim, never summarised. The first
   directive of a new workflow is always `RECORD_AUDIT` for exactly this.
7. Application code goes at the workspace root. Only lifecycle documentation
   goes under `aidlc-docs/`.
8. Validate content before writing it (valid Markdown, Mermaid parses, code
   blocks tagged). If a diagram will not validate, write the text fallback and
   record a `content_validation` event — never block the workflow on it.

## Directive playbook

| Directive | What you do | Settle with |
|---|---|---|
| `RECORD_AUDIT` | nothing but log — copy the user's raw input verbatim | `interaction` |
| `RESUME_SESSION` | read every path in `context_to_load`, then post a short welcome-back summary of where the workflow stands | `resume` |
| `ASSESS_CONDITIONAL` | judge the stage against `payload.include_criteria` / `skip_criteria`; when genuinely unsure, include it (`payload.default_on_doubt`) | `assessment` (`include`, `rationale`) |
| `RUN_STAGE` | read `context_to_load` first, then write every path in `payload.required_artifacts` at the directive's `depth` | `stage_completed` (or `error`) |
| `ASK_QUESTIONS` | write the question file at `payload.path`: numbered multiple-choice questions, each followed by a blank `[Answer]:` line; attach it and ask the user | `questions_published` |
| `AWAIT_ANSWERS` | `message_user(block_on_user=true)` pointing at the file; when the user answers, write their answers into the file after the `[Answer]:` tags | `answers_received` (or `ambiguity_detected`) |
| `AWAIT_APPROVAL` | `message_user(block_on_user=true)` with `payload.options` as the choices — exactly two, no invented third | `approval_response` (`decision`, verbatim `user_input`) |
| `SKIP_STAGE` | record the skip with the rationale the engine gives you | `stage_skipped` |
| `REMEDIATE` | run `payload.recovery` for the named failing check; nothing else | `recovery` (or `error`) |
| `CONFIRM_CHANGE` | state the impact of the requested change and get explicit confirmation before acting on it | `change_confirmed` |
| `ESCALATE_HUMAN` | `message_user(block_on_user=true)` — the task needs credentials or access you do not have | `human_task` (`resolved`) |
| `HALT_COMPLETE` | open the PR (`fetch_pr_template`, then `git_create_pr`) including `aidlc-docs/`, then report | `workflow_completed` |

## Devin bindings

- Mirror the lifecycle in the task list: `python3 -m aidlc --root <workspace>
  status` prints the projected plan; create one task per planned stage and keep
  exactly one `in_progress` — the one the current directive names.
- Gates are blocking messages. `AWAIT_APPROVAL`, `AWAIT_ANSWERS` and
  `ESCALATE_HUMAN` all end the turn with `message_user(block_on_user=true)`;
  use `content_type="user_question"` with `payload.options` for approvals.
- Questions live in files, not in chat. Attach the file and cite it; read the
  answers back out of the file so the artifact and the conversation cannot
  diverge.
- `build_and_test` on a unit with a UI: hand off to `testing_agent` rather than
  driving the browser yourself, then record its verdict in the event.
- A mid-flight user message is an event, not a detour: record it (as
  `interaction`, or `change_request` if it asks for a change) and call `next`.

## Recovering

```bash
python3 -m aidlc --root <workspace> status     # plan projection + failing checks
python3 -m aidlc --root <workspace> validate   # stage graph self-check
python3 -m aidlc --root <workspace> rebuild    # regenerate state/audit from the ledger
```

The append-only ledger (`aidlc-docs/.aidlc/ledger.jsonl`) is the source of
truth; both Markdown files are projections of it and can always be rebuilt.
