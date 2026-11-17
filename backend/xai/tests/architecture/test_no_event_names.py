"""K1, K4 and the reports know no event by name: K1 reads every rule from ``EventSpec``, the others
from the contract.

String literals of the K1 core, of the adapters, of K4 and of the reports must not name a seed
event; docstrings and comments may, as examples (NFR-K4-03). The prompts of the reports name no
event either: there are two prompts in all, none per event.
"""

import ast
import re
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
PACKAGES = ("k1_harvester", "adapters", "k4_planner", "reporting", "k5_report1")
PROMPTS_DIR = XAI_DIR / "resources" / "prompts"


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


def test_no_event_is_named_in_the_prompts() -> None:
    prompts = sorted(PROMPTS_DIR.glob("*.txt"))
    found = [
        f"{path.name}: {event!r}"
        for path in prompts
        for event in SEED_EVENTS
        if re.search(rf"\b{re.escape(event)}\b", path.read_text(encoding="utf-8"), re.IGNORECASE)
    ]

    assert prompts and found == []
