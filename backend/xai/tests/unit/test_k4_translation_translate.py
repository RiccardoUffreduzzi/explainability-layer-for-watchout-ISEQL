"""``translate``: the expected files, and what every translation guarantees."""

from functools import cache
from pathlib import Path

import pytest

from xai.contract.ids import step_id_of
from xai.contract.plan import IN_REPORT2, StepType
from xai.k4_planner.translation import translate, translation_from_data, translation_to_data
from xai.k4_planner.view import SourceOfTruthView
from xai.tests.k4_support import (
    GOLDEN_NAMES,
    REAL_SOURCE_PATHS,
    expected_translation,
    golden_source,
    real_source,
    view_of,
)


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_translate_gives_the_expected_file(name: str) -> None:
    assert translation_to_data(translate(view_of(name))) == expected_translation(name)


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_an_expected_file_reads_back_as_the_translation(name: str) -> None:
    assert translation_from_data(expected_translation(name)) == translate(view_of(name))


@cache
def _golden_of_event() -> dict[str, str]:
    return {golden_source(name).event.event_id: name for name in GOLDEN_NAMES}


@pytest.mark.parametrize("path", REAL_SOURCE_PATHS, ids=lambda p: p.name)
def test_a_real_source_translates_like_its_golden_draft(path: Path) -> None:
    document = real_source(path)
    name = _golden_of_event().get(document.event.event_id)
    if name is None:
        pytest.skip("no golden draft of this row")

    assert translation_to_data(translate(SourceOfTruthView.of(document))) == expected_translation(name)


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_what_every_translation_guarantees(name: str) -> None:
    view = view_of(name)
    translation = translate(view)
    excluded = {e.constraint_id for e in translation.excluded}

    for branch in translation.branches:
        steps = {step.step_id: step for step in branch.steps}
        nodes = [n.constraint_id for n in view.nodes_of(branch.branch)]
        # one step per node of the branch, named after it
        assert sorted(step_id_of(c) for c in nodes) == sorted(steps)
        assert all(s.construct_ is not None and s.step_id == step_id_of(s.construct_) for s in steps.values())
        # no limit, reinforcement or provenance step: the planner adds them
        assert not {s.type for s in steps.values()} & {
            StepType.LIMIT,
            StepType.REINFORCEMENT,
            StepType.PROVENANCE,
        }
        assert all(s.in_report2 is IN_REPORT2[s.type] for s in steps.values())
        # dependencies inside the branch, made before the step; the conclusion last
        made: set[str] = set()
        for step in branch.steps:
            assert set(step.depends_on) <= made
            made.add(step.step_id)
        assert branch.conclusion == branch.steps[-1].step_id
        assert steps[branch.conclusion].type is StepType.CONCLUSION
        assert not excluded & set(nodes)
    assert len(translation.excluded) + sum(len(b.steps) for b in translation.branches) == len(view.nodes)
