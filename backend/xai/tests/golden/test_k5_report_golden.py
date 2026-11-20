"""Report 1 of the golden plans of K4, byte for byte: the LLM's input, the prompt and the report.

For each golden plan ``<name>``:

- ``tests/data/k5/input/<name>.json``: the input of the LLM (plan, values, entities, glossary);
- ``tests/data/k5/prompt/<name>.txt``: the whole prompt of Report 1;
- ``tests/data/k5/report/<name>.md`` and ``.json``: the report rendered from the text written by
  hand in ``tests/data/k5/text/<name>.txt``, as if the LLM had answered it, with the key frame
  (``StillFrames``: fixed bytes in place of the frame of the video).

Regenerate them with ``XAI_UPDATE_GOLDEN=1 pytest tests/golden`` and review the diff.
"""

import os
from pathlib import Path

import pytest

from xai.contract.report import dump_report
from xai.tests.k5_support import (
    INPUT_DIR,
    NAMES,
    PROMPT_DIR,
    REPORT_DIR,
    ScriptedModel,
    StillFrames,
    hand_text,
    input_of,
    pair_of,
    writer,
)

UPDATE = os.environ.get("XAI_UPDATE_GOLDEN") == "1"


def _check(path: Path, text: str) -> None:
    if UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize("name", NAMES)
def test_the_input_of_the_llm_is_the_expected_one(name: str) -> None:
    _check(INPUT_DIR / f"{name}.json", input_of(name).to_json() + "\n")


@pytest.mark.parametrize("name", NAMES)
def test_the_prompt_is_the_expected_one(name: str) -> None:
    report_writer = writer(ScriptedModel([]))

    _check(PROMPT_DIR / f"{name}.txt", report_writer.prompt_of(input_of(name)) + "\n")


@pytest.mark.parametrize("name", NAMES)
def test_the_hand_written_text_gives_the_expected_report(name: str) -> None:
    written = writer(ScriptedModel([hand_text(name)]), frames=StillFrames()).write(*pair_of(name))

    _check(REPORT_DIR / f"{name}.md", written.markdown)
    _check(REPORT_DIR / f"{name}.json", dump_report(written.report))
