"""Structural tests for the package boundary (ARCH-02) and the router boundary
(ARCH-07).

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


# ---------------------------------------------------------------------------
# ARCH-07 - routers translate HTTP, they do not read the database
# ---------------------------------------------------------------------------

ROUTER_ROOT = APP_ROOT / "routers"

#: Routers may name the session type for their `Depends(get_db)` signatures.
#: Everything else under `sqlalchemy` is a query builder and belongs in services.
ALLOWED_SQLALCHEMY_MODULES = {"sqlalchemy.ext.asyncio"}


def iter_router_trees():
    """Yield `(path, tree)` for every router module."""
    for path in sorted(ROUTER_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path, ast.parse(path.read_text(encoding="utf-8"))


def _imported_modules(tree: ast.AST) -> list[tuple[int, str]]:
    """Every absolute or relative module name an `import`/`from ... import` names."""
    names: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                # `from ..db_models import Manga` inside `app.routers` -> app.db_models
                module = "." * node.level + module
            names.append((node.lineno, module))
    return names


def test_routers_do_not_import_sql_query_builders():
    """A router may import `AsyncSession` and nothing else from SQLAlchemy.

    `select`, `text`, `func`, `or_`, `update` and friends build the statement,
    which is the service layer's job (ARCH-07). The check is on the import, not
    on the resulting source text, so a docstring mentioning `text()` does not
    fail it.
    """
    offenders = [
        f"{path.name}:{line} -> {module}"
        for path, tree in iter_router_trees()
        for line, module in _imported_modules(tree)
        if module.startswith("sqlalchemy") and module not in ALLOWED_SQLALCHEMY_MODULES
    ]
    assert not offenders, (
        "routers must not build SQL; move the statement into app/services/ (ARCH-07). "
        "Offending imports: " + "; ".join(offenders)
    )


def test_routers_do_not_import_the_orm_models():
    """Routers stay out of persistence, so they cannot filter on a column either."""
    offenders = [
        f"{path.name}:{line} -> {module}"
        for path, tree in iter_router_trees()
        for line, module in _imported_modules(tree)
        if "db_models" in module
    ]
    assert not offenders, (
        "routers must not import app.db_models (ARCH-07); ask a service for the rows. "
        "Offending imports: " + "; ".join(offenders)
    )


def test_routers_do_not_execute_statements():
    """No `.execute(` call in a router, whatever it was handed.

    Importing nothing from SQLAlchemy does not stop `await db.execute(some_string)`
    or a helper smuggled in unparsed; this closes that half.
    """
    offenders = [
        f"{path.name}:{node.lineno}"
        for path, tree in iter_router_trees()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "executemany"}
    ]
    assert not offenders, (
        "routers must not execute statements (ARCH-07). Offending calls: " + "; ".join(offenders)
    )


@pytest.mark.parametrize(
    "module",
    [
        "app.services.catalog",
        "app.services.featured",
    ],
)
def test_catalogue_reads_are_importable_without_a_database(module):
    """The modules the routers now delegate to must not need a connection to load."""
    __import__(module)


# ---------------------------------------------------------------------------
# ARCH-10 - no service module is a god module, and each one owns its functions
# ---------------------------------------------------------------------------

SERVICES_ROOT = APP_ROOT / "services"

#: `retrieval.py` was 1,159 lines and held six responsibilities. The split is
#: only useful if it stays split, so the owner of each function is pinned here:
#: a name that reappears in `retrieval.py` as a convenience re-export recreates
#: the thing that was removed (two homes for one rule).
SERVICE_OWNERS = {
    "app.services.query_filters": [
        "build_genre_sql_condition",
        "apply_filter_criteria",
        "generate_filter_hash",
    ],
    "app.services.tag_alignment": [
        "DEFAULT_CATEGORY_WEIGHTS",
        "compute_category_aware_tag_alignment",
        "build_tag_alignment_sql",
    ],
    "app.services.title_match": [
        "is_confident_title_match",
        "find_exact_title",
        "find_title_suggestion",
    ],
    "app.services.diversity": [
        "franchise_key",
        "apply_diversity_filtering",
    ],
    "app.services.roulette": [
        "sample_candidates_from_db",
        "retrieve_roulette_manga",
    ],
    "app.services.retrieval": [
        "apply_ann_settings",
        "compute_pool_limit",
        "similar_edges_are_fresh",
        "retrieve_similar_manga",
    ],
}

#: The ceiling is deliberately generous: it is a tripwire for a module growing
#: back into a god module, not a style rule.
SERVICE_LINE_CEILING = 500


@pytest.mark.parametrize("module", sorted(SERVICE_OWNERS))
def test_each_split_module_owns_its_functions(module):
    """Every name in the owner map is defined by that module, not re-exported."""
    imported = __import__(module, fromlist=["_"])
    missing = [name for name in SERVICE_OWNERS[module] if not hasattr(imported, name)]
    assert not missing, f"{module} does not define {missing} (ARCH-10)"


def _defined_names(module: str) -> set[str]:
    """Names *defined* by a module's own source (imports do not count)."""
    path = SERVICES_ROOT / (module.split(".")[-1] + ".py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_the_moved_names_have_one_home():
    """A name may only be *defined* in its owner module: one rule, one home.

The check reads the source with `ast` rather than `hasattr`, because
    `retrieval` legitimately *imports* `apply_filter_criteria` — importing is how
    a module uses a rule, defining it twice is how the rule drifts.
    """
    homes: dict[str, list[str]] = {}
    for module, names in SERVICE_OWNERS.items():
        defined = _defined_names(module)
        for name in names:
            assert name in defined, f"{module} does not define {name} (ARCH-10)"
            homes.setdefault(name, []).append(module)

    duplicated = [f"{name}: {', '.join(modules)}" for name, modules in homes.items() if len(modules) > 1]
    assert not duplicated, "one name, two homes (ARCH-10): " + "; ".join(duplicated)


def test_no_service_module_exceeds_the_line_ceiling():
    oversized = [
        f"{path.name}: {len(path.read_text(encoding='utf-8').splitlines())} lines"
        for path in sorted(SERVICES_ROOT.glob("*.py"))
        if "__pycache__" not in path.parts
        and len(path.read_text(encoding="utf-8").splitlines()) > SERVICE_LINE_CEILING
    ]
    assert not oversized, (
        f"a service module grew past {SERVICE_LINE_CEILING} lines; split it rather "
        "than growing it (ARCH-10). " + "; ".join(oversized)
    )
