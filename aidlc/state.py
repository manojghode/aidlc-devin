"""Read-only view of the workspace.

``Snapshot.capture`` is the *only* way the engine sees the world. It hashes
everything it read, so the engine can prove it did not mutate anything while
deciding (see ``aidlc.engine``).

The append-only JSONL ledger under ``aidlc-docs/.aidlc/`` is the machine
representation of the audit trail; ``aidlc-state.md`` and ``audit.md`` are the
human-readable renderings of the same facts, written by ``aidlc.recorder``.

Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from . import artifacts, stages
from .model import Depth, EventKind, StageStatus

INTERNAL_NAME = ".aidlc"
INTERNAL_DIR = f"aidlc-docs/{INTERNAL_NAME}"
LEDGER_PATH = f"{INTERNAL_DIR}/ledger.jsonl"
AUDIT_INDEX_PATH = f"{INTERNAL_DIR}/audit-index.json"

DEFAULT_UNIT = "main"

CODE_SUFFIXES = (
    ".java", ".py", ".js", ".ts", ".jsx", ".tsx", ".kt", ".kts", ".scala", ".groovy",
    ".go", ".rs", ".rb", ".php", ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".fs",
)
BUILD_FILES = (
    "pom.xml", "package.json", "build.gradle", "build.gradle.kts", "Cargo.toml",
    "go.mod", "pyproject.toml", "setup.py", "Gemfile", "composer.json", "CMakeLists.txt",
)
IGNORED_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target",
    ".mypy_cache", ".pytest_cache", ".idea", ".vscode", "aidlc-docs",
}
MAX_SCAN_ENTRIES = 20000
MAX_TEXT_BYTES = 262144


@dataclass(frozen=True)
class WorkspaceFingerprint:
    has_code: bool
    languages: Tuple[str, ...]
    build_systems: Tuple[str, ...]
    code_file_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_code": self.has_code,
            "languages": list(self.languages),
            "build_systems": list(self.build_systems),
            "code_file_count": self.code_file_count,
        }


@dataclass(frozen=True)
class Assessment:
    stage: str
    unit: Optional[str]
    include: bool
    depth: Depth
    rationale: str


@dataclass(frozen=True)
class Gatekeeping:
    """Outstanding gate state for one (stage, unit, part) triple."""

    prompt_pending: bool = False
    approved: bool = False
    changes_requested: bool = False


@dataclass(frozen=True)
class Snapshot:
    """An immutable, hashed observation of the workspace."""

    root: str
    files: Mapping[str, str]
    texts: Mapping[str, str]
    workspace: WorkspaceFingerprint
    ledger: Tuple[Mapping[str, Any], ...]
    audit_index: Mapping[str, Any]
    audit_actual: Mapping[str, Any]
    state_hash: str = field(default="", compare=False)

    # -- capture ------------------------------------------------------------

    @staticmethod
    def capture(root: "os.PathLike[str] | str") -> "Snapshot":
        root_path = Path(root).resolve()
        files, texts = _hash_tree(root_path / artifacts.DOCS_ROOT, root_path)
        workspace = _fingerprint_workspace(root_path)
        ledger = _read_ledger(root_path / LEDGER_PATH)
        audit_index = _read_json(root_path / AUDIT_INDEX_PATH, default={})
        audit_actual = _measure_audit(root_path / artifacts.AUDIT_PATH)
        snapshot = Snapshot(
            root=str(root_path),
            files=files,
            texts=texts,
            workspace=workspace,
            ledger=ledger,
            audit_index=audit_index,
            audit_actual=audit_actual,
        )
        return snapshot.with_hash()

    def with_hash(self) -> "Snapshot":
        material = json.dumps(
            {
                "files": dict(sorted(self.files.items())),
                "workspace": self.workspace.to_dict(),
                "ledger": [dict(sorted(e.items())) for e in self.ledger],
                "audit": dict(sorted(self.audit_actual.items())),
            },
            sort_keys=True,
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return Snapshot(
            root=self.root,
            files=self.files,
            texts=self.texts,
            workspace=self.workspace,
            ledger=self.ledger,
            audit_index=self.audit_index,
            audit_actual=self.audit_actual,
            state_hash=digest,
        )

    # -- filesystem queries -------------------------------------------------

    def exists(self, relpath: str) -> bool:
        if relpath in self.files:
            return True
        prefix = relpath.rstrip("/") + "/"
        return any(p.startswith(prefix) for p in self.files)

    def non_empty(self, relpath: str) -> bool:
        digest = self.files.get(relpath)
        if digest is None:
            prefix = relpath.rstrip("/") + "/"
            return any(p.startswith(prefix) for p in self.files)
        return digest != _EMPTY_MARKER

    def text(self, relpath: str) -> str:
        return self.texts.get(relpath, "")

    def artifact_path(self, artifact_id: str, unit: Optional[str] = None) -> str:
        return artifacts.resolve(artifact_id, unit)

    def artifact_exists(self, artifact_id: str, unit: Optional[str] = None) -> bool:
        return self.exists(self.artifact_path(artifact_id, unit))

    def initialized(self) -> bool:
        return self.exists(artifacts.STATE_PATH)

    # -- ledger queries -----------------------------------------------------

    def events(self, *kinds: EventKind) -> Tuple[Mapping[str, Any], ...]:
        if not kinds:
            return self.ledger
        wanted = {k.value for k in kinds}
        return tuple(e for e in self.ledger if e.get("kind") in wanted)

    def last_event(self) -> Optional[Mapping[str, Any]]:
        return self.ledger[-1] if self.ledger else None

    def brownfield(self) -> bool:
        for event in reversed(self.events(EventKind.STAGE_COMPLETED)):
            if event.get("stage") == stages.WORKSPACE_DETECTION:
                recorded = event.get("fields", {}).get("brownfield")
                if recorded is not None:
                    return bool(recorded)
        return self.workspace.has_code

    def units(self) -> Tuple[str, ...]:
        for event in reversed(self.ledger):
            units = event.get("fields", {}).get("units")
            if units:
                return tuple(str(u) for u in units)
        return (DEFAULT_UNIT,)

    def unit_dependencies(self) -> Mapping[str, Tuple[str, ...]]:
        for event in reversed(self.ledger):
            deps = event.get("fields", {}).get("unit_dependencies")
            if deps:
                return {str(k): tuple(str(x) for x in v) for k, v in deps.items()}
        return {}

    def status(self, stage_id: str, unit: Optional[str] = None) -> StageStatus:
        unit = _unit_key(stage_id, unit)
        result = StageStatus.PENDING
        for event in self.ledger:
            if event.get("stage") != stage_id or event.get("unit") != unit:
                continue
            kind = event.get("kind")
            if kind == EventKind.STAGE_STARTED.value:
                result = StageStatus.IN_PROGRESS
            elif kind == EventKind.STAGE_COMPLETED.value:
                if event.get("fields", {}).get("part"):
                    continue
                result = StageStatus.COMPLETED
            elif kind == EventKind.STAGE_SKIPPED.value:
                result = StageStatus.SKIPPED
            elif kind == EventKind.STAGE_RESTARTED.value:
                result = StageStatus.IN_PROGRESS
        return result

    def completed(self, stage_id: str, unit: Optional[str] = None) -> bool:
        return self.status(stage_id, unit) is StageStatus.COMPLETED

    def settled(self, stage_id: str, unit: Optional[str] = None) -> bool:
        return self.status(stage_id, unit) in (StageStatus.COMPLETED, StageStatus.SKIPPED)

    def part_completed(self, stage_id: str, unit: Optional[str], part: str) -> bool:
        unit = _unit_key(stage_id, unit)
        for event in self.ledger:
            if (
                event.get("kind") == EventKind.STAGE_COMPLETED.value
                and event.get("stage") == stage_id
                and event.get("unit") == unit
                and event.get("fields", {}).get("part") == part
            ):
                return True
        return False

    def assessment(self, stage_id: str, unit: Optional[str] = None) -> Optional[Assessment]:
        unit = _unit_key(stage_id, unit)
        found: Optional[Assessment] = None
        for event in self.events(EventKind.ASSESSMENT):
            if event.get("stage") != stage_id or event.get("unit") != unit:
                continue
            fields = event.get("fields", {})
            found = Assessment(
                stage=stage_id,
                unit=unit,
                include=bool(fields.get("include")),
                depth=_depth(fields.get("depth")),
                rationale=str(fields.get("rationale", "")),
            )
        return found

    def depth_for(self, stage_id: str, unit: Optional[str] = None) -> Depth:
        found = self.assessment(stage_id, unit)
        if found:
            return found.depth
        for event in reversed(self.events(EventKind.ASSESSMENT, EventKind.STAGE_COMPLETED)):
            depth = event.get("fields", {}).get("default_depth")
            if depth:
                return _depth(depth)
        return Depth.STANDARD

    def questions_published_for(self, path: str) -> bool:
        return any(
            e.get("fields", {}).get("path") == path
            for e in self.events(EventKind.QUESTIONS_PUBLISHED)
        )

    def gate(self, stage_id: str, unit: Optional[str], part: Optional[str] = None) -> Gatekeeping:
        unit = _unit_key(stage_id, unit)
        prompt_pending = False
        approved = False
        changes_requested = False
        for event in self.ledger:
            if event.get("stage") != stage_id or event.get("unit") != unit:
                continue
            fields = event.get("fields", {})
            if part is None:
                if fields.get("part"):
                    continue
            elif fields.get("part") != part:
                continue
            kind = event.get("kind")
            if kind == EventKind.APPROVAL_PROMPT.value:
                prompt_pending = True
                approved = False
                changes_requested = False
            elif kind == EventKind.APPROVAL_RESPONSE.value:
                prompt_pending = False
                decision = str(fields.get("decision", "")).lower()
                approved = decision in ("approve", "approved", "continue", "yes")
                changes_requested = not approved
            elif kind == EventKind.STAGE_RESTARTED.value:
                prompt_pending = approved = changes_requested = False
        return Gatekeeping(prompt_pending, approved, changes_requested)

    def open_questions(self) -> Tuple[Mapping[str, Any], ...]:
        """Question files published but not yet answered."""

        published: Dict[str, Mapping[str, Any]] = {}
        for event in self.events(EventKind.QUESTIONS_PUBLISHED, EventKind.ANSWERS_RECEIVED):
            path = str(event.get("fields", {}).get("path", ""))
            if not path:
                continue
            if event.get("kind") == EventKind.QUESTIONS_PUBLISHED.value:
                published[path] = event
            else:
                published.pop(path, None)
        return tuple(published.values())

    def open_ambiguities(self) -> Tuple[Mapping[str, Any], ...]:
        detected: Dict[str, Mapping[str, Any]] = {}
        for event in self.events(EventKind.AMBIGUITY_DETECTED, EventKind.AMBIGUITY_RESOLVED):
            key = str(event.get("fields", {}).get("id")
                      or event.get("fields", {}).get("description", ""))
            if event.get("kind") == EventKind.AMBIGUITY_DETECTED.value:
                detected[key] = event
            else:
                detected.pop(key, None)
        return tuple(detected.values())

    def open_change_requests(self) -> Tuple[Mapping[str, Any], ...]:
        pending: Dict[str, Mapping[str, Any]] = {}
        for event in self.events(EventKind.CHANGE_REQUEST, EventKind.CHANGE_CONFIRMED):
            key = str(event.get("fields", {}).get("request", ""))
            if event.get("kind") == EventKind.CHANGE_REQUEST.value:
                pending[key] = event
            else:
                pending.pop(key, None)
        return tuple(pending.values())

    def open_human_tasks(self) -> Tuple[Mapping[str, Any], ...]:
        open_tasks: Dict[str, Mapping[str, Any]] = {}
        for event in self.events(EventKind.HUMAN_TASK, EventKind.RECOVERY):
            fields = event.get("fields", {})
            key = str(fields.get("description", ""))
            if event.get("kind") == EventKind.HUMAN_TASK.value:
                if fields.get("resolved"):
                    open_tasks.pop(key, None)
                else:
                    open_tasks[key] = event
            elif fields.get("resolves_human_task"):
                open_tasks.pop(str(fields.get("resolves_human_task")), None)
        return tuple(open_tasks.values())

    def initial_request_logged(self) -> bool:
        for event in self.events(EventKind.INTERACTION):
            if event.get("fields", {}).get("user_input"):
                return True
        return False

    def paused(self) -> bool:
        last = self.last_event()
        return last is not None and last.get("kind") == EventKind.PAUSE.value

    def extensions(self) -> Mapping[str, bool]:
        decided: Dict[str, bool] = {}
        for event in self.events(EventKind.EXTENSION_DECISION):
            fields = event.get("fields", {})
            decided[str(fields.get("extension"))] = bool(fields.get("enabled"))
        return decided

    def workflow_completed(self) -> bool:
        return bool(self.events(EventKind.WORKFLOW_COMPLETED))


_EMPTY_MARKER = "empty"


def _unit_key(stage_id: str, unit: Optional[str]) -> Optional[str]:
    stage = stages.get(stage_id)
    return unit if stage.per_unit else None


def _depth(value: Any) -> Depth:
    try:
        return Depth(str(value).lower())
    except ValueError:
        return Depth.STANDARD


def _hash_tree(directory: Path, root: Path) -> Tuple[Dict[str, str], Dict[str, str]]:
    digests: Dict[str, str] = {}
    texts: Dict[str, str] = {}
    if not directory.is_dir():
        return digests, texts
    for dirpath, dirnames, filenames in os.walk(directory):
        # The internal directory is the recorder's own bookkeeping (ledger, index,
        # lock). It is hashed separately, never as part of the document tree.
        dirnames[:] = sorted(d for d in dirnames if d != INTERNAL_NAME)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            try:
                data = path.read_bytes()
            except OSError:
                continue
            rel = str(path.relative_to(root)).replace(os.sep, "/")
            digests[rel] = _EMPTY_MARKER if not data.strip() else hashlib.sha256(data).hexdigest()
            if name.endswith(".md") and len(data) <= MAX_TEXT_BYTES:
                texts[rel] = data.decode("utf-8", errors="replace")
        if len(digests) > MAX_SCAN_ENTRIES:
            break
    return digests, texts


def _fingerprint_workspace(root: Path) -> WorkspaceFingerprint:
    languages: Set[str] = set()
    builds: Set[str] = set()
    count = 0
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS and not d.startswith("."))
        for name in filenames:
            scanned += 1
            if scanned > MAX_SCAN_ENTRIES:
                break
            suffix = Path(name).suffix
            if suffix in CODE_SUFFIXES:
                languages.add(suffix)
                count += 1
            if name in BUILD_FILES:
                builds.add(name)
        if scanned > MAX_SCAN_ENTRIES:
            break
    return WorkspaceFingerprint(
        has_code=count > 0 or bool(builds),
        languages=tuple(sorted(languages)),
        build_systems=tuple(sorted(builds)),
        code_file_count=count,
    )


def _read_ledger(path: Path) -> Tuple[Mapping[str, Any], ...]:
    if not path.is_file():
        return ()
    events: List[Mapping[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return tuple(events)


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _measure_audit(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "length": 0, "prefix_sha256": ""}
    data = path.read_bytes()
    return {
        "exists": True,
        "length": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def prefix_digest(path: Path, length: int) -> str:
    with path.open("rb") as handle:
        return hashlib.sha256(handle.read(length)).hexdigest()


def planned_units(snapshot: Snapshot) -> Sequence[str]:
    return snapshot.units()
