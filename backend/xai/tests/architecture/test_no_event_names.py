"""K1 knows no event by name: it reads every rule from ``EventSpec``.

String literals of the K1 core and of the adapters must not name a seed event;
docstrings and comments may, as examples.
"""

import ast
from pathlib import Path

import pytest

from xai.tests.support import XAI_DIR

SEED_EVENTS = (
    "fight",
    "gunshot_or_explosion",
    "handoff",
    "suspicious_near_vehicle",
    "vehicle_collision",
    "vehicle_escape",
)
PACKAGES = ("k1_harvester", "adapters")


def _code_strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    ]


@pytest.mark.parametrize("package", PACKAGES)
def test_no_event_is_named_in_code(package: str) -> None:
    found = [
        f"{path.relative_to(XAI_DIR)}: {text!r}"
        for path in sorted((XAI_DIR / package).rglob("*.py"))
        for text in _code_strings(path)
        if any(event in text for event in SEED_EVENTS)
    ]

    assert found == []


def test_the_scan_sees_code_strings_and_skips_docstrings(tmp_path: Path) -> None:
    module = tmp_path / "m.py"
    module.write_text('"""About handoff."""\nRULE = "handoff/A"\n', encoding="utf-8")

    assert _code_strings(module) == ["handoff/A"]
