"""Where the stages of the pipeline keep their files."""

from pathlib import Path

from xai.k2.stage import k2_path as k2_stage_path
from xai.pipeline.paths import k2_path, k4_path, k4_path_of_source

DRAFT = Path("out/an_1/handoff/ev_0123456789ab.json")


def test_the_stages_keep_their_files_side_by_side() -> None:
    assert k2_path(DRAFT) == Path("out/an_1/k2/handoff/ev_0123456789ab.json")
    assert k4_path(DRAFT) == Path("out/an_1/k4/handoff/ev_0123456789ab.json")


def test_the_path_of_k2_is_the_one_k2_writes_to() -> None:
    assert k2_path(DRAFT) == k2_stage_path(DRAFT)


def test_the_plan_that_goes_with_a_source_of_truth() -> None:
    assert k4_path_of_source(k2_path(DRAFT)) == k4_path(DRAFT)
