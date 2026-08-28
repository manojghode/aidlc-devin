"""The three architectural invariants, tested directly.

1. the engine is authoritative and emits exactly one typed directive per turn;
2. the engine is strictly read-only (state hash unchanged, nothing written);
3. the package imports nothing outside the platform runtime.
"""

from __future__ import annotations

import ast
import sys
import unittest
from typing import List, Set

from helpers import REPO_ROOT, WorkspaceCase  # noqa: E402

from aidlc import checks, engine  # noqa: E402
from aidlc.model import Directive, EngineMutatedState  # noqa: E402
from aidlc.state import Snapshot  # noqa: E402

PACKAGE = REPO_ROOT / "aidlc"


class NoThirdPartyImports(unittest.TestCase):
    """Hard constraint: platform runtime built-ins only."""

    def test_every_import_is_stdlib_or_local(self) -> None:
        stdlib: Set[str] = set(sys.stdlib_module_names)
        offenders = []
        for path in sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        if root not in stdlib and root != "aidlc":
                            offenders.append(f"{path.name}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.level:  # relative import inside the package
                        continue
                    root = (node.module or "").split(".")[0]
                    if root and root not in stdlib and root != "aidlc":
                        offenders.append(f"{path.name}: from {node.module} import ...")
        self.assertEqual([], offenders)

    def test_no_dependency_manifest_declares_requirements(self) -> None:
        for name in ("requirements.txt", "poetry.lock", "Pipfile", "uv.lock"):
            self.assertFalse((REPO_ROOT / name).exists(), f"{name} must not exist")


class OneDirectivePerTurn(WorkspaceCase):
    def test_returns_a_single_typed_directive(self) -> None:
        directive = self.next_directive()
        self.assertIsInstance(directive, Directive)
        self.assertNotIsInstance(directive, (list, tuple, set))

    def test_repeated_calls_are_deterministic(self) -> None:
        first = self.next_directive()
        second = self.next_directive()
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_directive_declares_what_settles_it(self) -> None:
        directive = self.next_directive()
        self.assertTrue(directive.settles)
        self.assertTrue(directive.reason)

    def test_every_directive_in_a_full_run_is_singular(self) -> None:
        for directive in self.run_lifecycle():
            self.assertIsInstance(directive, Directive)


class EngineIsReadOnly(WorkspaceCase):
    def test_state_hash_is_unchanged_across_the_call(self) -> None:
        before = Snapshot.capture(self.root).state_hash
        self.next_directive()
        self.assertEqual(before, Snapshot.capture(self.root).state_hash)

    def test_no_file_is_created_or_modified(self) -> None:
        def listing() -> Set[str]:
            return {
                f"{p.relative_to(self.root)}:{p.stat().st_size}"
                for p in self.root.rglob("*") if p.is_file()
            }

        self.settle(self.next_directive())
        before = listing()
        for _ in range(3):
            engine.step(self.root)
        self.assertEqual(before, listing())

    def test_mutation_during_evaluation_is_detected(self) -> None:
        original = engine.decide

        def mutating(snapshot: Snapshot) -> Directive:
            (self.root / "aidlc-docs").mkdir(parents=True, exist_ok=True)
            (self.root / "aidlc-docs" / "sneaky.md").write_text("x", encoding="utf-8")
            return original(snapshot)

        engine.decide = mutating
        self.addCleanup(setattr, engine, "decide", original)
        with self.assertRaises(EngineMutatedState):
            engine.step(self.root)

    def test_checks_never_write(self) -> None:
        self.settle(self.next_directive())
        before = Snapshot.capture(self.root).state_hash
        checks.run_all(Snapshot.capture(self.root))
        self.assertEqual(before, Snapshot.capture(self.root).state_hash)


class EngineNeverCallsAModel(unittest.TestCase):
    def test_no_network_or_subprocess_capability_is_imported(self) -> None:
        forbidden = {"socket", "http", "urllib", "subprocess", "ssl", "ftplib", "smtplib",
                     "asyncio", "webbrowser", "ctypes"}
        offenders: List[str] = []
        for path in sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    names = [(node.module or "").split(".")[0]]
                offenders.extend(f"{path.name}: {n}" for n in names if n in forbidden)
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
