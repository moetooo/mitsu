"""Structural tests for the package boundary (ARCH-02).

`app.ingestion` and `app.sync` used to import each other. Nothing failed at
import time -- Python coped -- so the cycle was invisible until you tried to
move one package without the other. The shared primitives now live in
`app.core` and the dependency points one way:

    sync  ->  ingestion  ->  core

These tests read the import graph off the source with `ast` rather than trying
to import modules, so a violation is reported with the file and line that
causes it, and the test does not depend on a database or an event loop.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"


def _module_name(path: Path) -> str:
    """`app/sync/budget.py` -> `app.sync.budget`, `app/sync/__init__.py` -> `app.sync`."""
    parts = list(path.relative_to(APP_ROOT.parent).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _package_of(module: str, is_package: bool) -> list[str]:
    parts = module.split(".")
    return parts if is_package else parts[:-1]


def _resolve(importer_package: list[str], node: ast.ImportFrom) -> str:
    """Resolve a relative `from ... import` to an absolute dotted module name."""
    if not node.level:
        return node.module or ""
    base = importer_package[: len(importer_package) - (node.level - 1)]
    if node.module:
        base = base + node.module.split(".")
    return ".".join(base)


def iter_imports():
    """Yield `(importer_module, imported_module, line)` for every relative import."""
    for path in sorted(APP_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        module = _module_name(path)
        package = _package_of(module, path.name == "__init__.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                target = _resolve(package, node)
                if target:
                    yield module, target, node.lineno


def test_no_module_imports_a_package_that_drives_it():
    """`ingestion` must not import `sync`: `sync` already imports `ingestion`."""
    offenders = [
        f"{importer}:{line} -> {target}"
        for importer, target, line in iter_imports()
        if importer.split(".")[1] == "ingestion" and target.split(".")[1] == "sync"
    ]
    assert not offenders, (
        "app.ingestion must not import app.sync (ARCH-02). "
        "Shared primitives belong in app.core. Offending imports: " + "; ".join(offenders)
    )


def test_core_does_not_depend_on_the_packages_that_use_it():
    """`app.core` is a leaf: it may use `db`, `config` and `db_models`, nothing above it."""
    allowed = {"config", "db", "db_models"}
    offenders = [
        f"{importer}:{line} -> {target}"
        for importer, target, line in iter_imports()
        if importer.split(".")[1] == "core"
        and len(target.split(".")) > 1
        and target.split(".")[1] not in allowed
    ]
    assert not offenders, (
        "app.core must stay a leaf module set; it may only use "
        + ", ".join(sorted(allowed))
        + ". Offending imports: "
        + "; ".join(offenders)
    )


def test_no_package_level_import_cycle():
    """No two `app.<package>` subtrees may depend on each other in both directions."""
    edges: dict[str, set[str]] = {}
    for importer, target, _line in iter_imports():
        source = ".".join(importer.split(".")[:2])
        destination = ".".join(target.split(".")[:2])
        if source != destination and "." in target:
            edges.setdefault(source, set()).add(destination)

    cycles = sorted(
        f"{a} <-> {b}"
        for a, destinations in edges.items()
        for b in destinations
        if a in edges.get(b, set()) and a < b
    )
    assert not cycles, "package-level import cycle(s) in app/: " + ", ".join(cycles)


@pytest.mark.parametrize(
    "module",
    [
        "app.core.budget",
        "app.core.identity",
        "app.core.schema",
    ],
)
def test_shared_primitives_live_in_core(module):
    """The three modules ingestion needs must be importable without touching `app.sync`."""
    __import__(module)
