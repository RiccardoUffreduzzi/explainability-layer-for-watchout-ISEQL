"""Import rules of the architecture.

- ``xai.contract`` is the shared kernel: standard library and pydantic only.
- Only ``xai.adapters.watchout`` imports ``sqlite3`` or WatchOut's packages.
- The K1 core (``xai.k1_harvester``) does not import adapters, the CLI or the pipeline.
- No WatchOut module imports ``xai``.

Imports are read with ``ast``, so the rules hold for modules that are not imported by
any test. Tests are exempt from the first three rules: conformance tests import WatchOut.
"""

import ast
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from xai.tests.support import WATCHOUT_SRC_DIR, XAI_DIR

THIRD_PARTY_ALLOWED_IN_CONTRACT = {"pydantic", "pydantic_core", "annotated_types", "typing_extensions"}


@dataclass(frozen=True)
class Module:
    name: str
    path: Path
    imports: frozenset[str]


def watchout_packages() -> frozenset[str]:
    """Top-level names importable from backend/src (``api``, ``service``, ``iseql`` …)."""
    names = {p.name for p in WATCHOUT_SRC_DIR.iterdir() if (p / "__init__.py").exists()}
    names |= {p.stem for p in WATCHOUT_SRC_DIR.glob("*.py") if p.stem != "__init__"}
    return frozenset(names)


def module_name(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imported_modules(source: str, module: str, is_package: bool) -> frozenset[str]:
    """Absolute names of every module imported by ``source``, relative imports resolved."""
    package = module if is_package else module.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = package.split(".")
                base_parts = base_parts[: len(base_parts) - (node.level - 1)]
                base = ".".join(base_parts)
                found.add(f"{base}.{node.module}" if node.module else base)
            elif node.module:
                found.add(node.module)
    return frozenset(found)


def iter_modules(root: Path, package_root: Path) -> Iterator[Module]:
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        name = module_name(path, package_root)
        source = path.read_text(encoding="utf-8")
        yield Module(name, path, imported_modules(source, name, path.name == "__init__.py"))


def top(name: str) -> str:
    return name.split(".")[0]


def is_within(name: str, package: str) -> bool:
    return name == package or name.startswith(package + ".")


def violations(module: Module, watchout: frozenset[str]) -> list[str]:
    """Rule violations of one ``xai`` module."""
    if is_within(module.name, "xai.tests"):
        return []
    found = []
    touches_watchout = {i for i in module.imports if top(i) in watchout or top(i) == "sqlite3"}
    if touches_watchout and not is_within(module.name, "xai.adapters.watchout"):
        found.append(f"{module.name} imports {sorted(touches_watchout)}: only xai.adapters.watchout may")
    if is_within(module.name, "xai.contract"):
        outside = {
            i
            for i in module.imports
            if not is_within(i, "xai.contract")
            and top(i) not in sys.stdlib_module_names
            and top(i) not in THIRD_PARTY_ALLOWED_IN_CONTRACT
        }
        if outside:
            found.append(
                f"{module.name} imports {sorted(outside)}: xai.contract uses stdlib and pydantic only"
            )
    if is_within(module.name, "xai.k1_harvester"):
        outer = {
            i
            for i in module.imports
            if any(is_within(i, p) for p in ("xai.adapters", "xai.cli", "xai.pipeline"))
        }
        if outer:
            found.append(
                f"{module.name} imports {sorted(outer)}: the K1 core sees WatchOut only through its ports"
            )
    return found


def xai_modules() -> list[Module]:
    return list(iter_modules(XAI_DIR, XAI_DIR.parent))


def test_scanner_sees_the_contract_package() -> None:
    names = {m.name for m in xai_modules()}

    assert {"xai.contract", "xai.contract.model", "xai.contract.primitives"} <= names


def test_scanner_resolves_relative_imports() -> None:
    source = "from . import ids\nfrom .model import ContractDraft\nfrom ..k1_harvester import ports\n"

    found = imported_modules(source, "xai.contract.serialization", is_package=False)

    assert found == {"xai.contract", "xai.contract.model", "xai.k1_harvester"}


def test_watchout_packages_are_found() -> None:
    assert {"api", "service", "iseql", "utils"} <= watchout_packages()


@pytest.mark.parametrize(
    ("name", "imports", "expected"),
    [
        ("xai.k1_harvester.service", {"sqlite3"}, "only xai.adapters.watchout may"),
        ("xai.k1_harvester.rule.readers", {"iseql.compiler"}, "only xai.adapters.watchout may"),
        ("xai.contract.model", {"yaml"}, "stdlib and pydantic only"),
        ("xai.contract.model", {"xai.k1_harvester.ports"}, "stdlib and pydantic only"),
        ("xai.k1_harvester.service", {"xai.adapters.watchout.reader"}, "only through its ports"),
    ],
)
def test_rules_catch_forbidden_imports(name: str, imports: set[str], expected: str) -> None:
    module = Module(name, Path(name), frozenset(imports))

    assert any(expected in v for v in violations(module, watchout_packages()))


@pytest.mark.parametrize(
    ("name", "imports"),
    [
        ("xai.adapters.watchout.engine", {"sqlite3", "iseql.compiler", "xai.k1_harvester.ports"}),
        ("xai.contract.model", {"typing", "pydantic", "xai.contract.ids"}),
        ("xai.k1_harvester.service", {"xai.contract", "xai.k1_harvester.ports"}),
        ("xai.tests.conformance.test_rules", {"sqlite3", "iseql.compiler"}),
    ],
)
def test_rules_allow_permitted_imports(name: str, imports: set[str]) -> None:
    module = Module(name, Path(name), frozenset(imports))

    assert violations(module, watchout_packages()) == []


def test_xai_modules_respect_the_import_rules() -> None:
    watchout = watchout_packages()

    found = [v for module in xai_modules() for v in violations(module, watchout)]

    assert found == []


def test_watchout_does_not_import_xai() -> None:
    offenders = [
        f"{module.path.relative_to(WATCHOUT_SRC_DIR)} imports {sorted(xai_imports)}"
        for module in iter_modules(WATCHOUT_SRC_DIR, WATCHOUT_SRC_DIR)
        if (xai_imports := {i for i in module.imports if top(i) == "xai"})
    ]

    assert offenders == []
