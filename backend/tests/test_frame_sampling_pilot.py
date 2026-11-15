from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "experiments" / "run_frame_sampling_pilot.py"
SPEC = importlib.util.spec_from_file_location("frame_sampling_pilot", RUNNER_PATH)
assert SPEC and SPEC.loader
pilot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pilot
SPEC.loader.exec_module(pilot)


def test_fixed_pilot_scene_manifest_has_one_scene_per_event() -> None:
    scenes = pilot.load_pilot_scenes()

    assert [scene.scene for scene in scenes] == [4, 7, 12, 15, 18, 21]
    assert [scene.filename for scene in scenes] == [
        "scene4.mp4", "scene7.mp4", "scene12.mp4", "scene15.mp4", "scene18.mp4", "scene21.mp4",
    ]
    assert scenes[4].pilot_event == "loitering"
    assert scenes[4].ground_truth_event == "suspicious_near_vehicle"


@pytest.mark.parametrize(
    ("sampling_hz", "stride", "expected"),
    [
        (0.5, 48, [0, 48, 96, 144, 192, 240]),
        (1.0, 24, list(range(0, 241, 24))),
        (2.0, 12, list(range(0, 241, 12))),
        (4.0, 6, list(range(0, 241, 6))),
    ],
)
def test_frame_selection_is_deterministic_from_source_frame_zero(sampling_hz, stride, expected) -> None:
    assert pilot.stride_for(sampling_hz) == stride
    assert pilot.sampled_frame_indices(241, stride) == expected


def test_existing_output_directory_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "2hz"
    target.mkdir()

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        pilot.create_new_output_directory(target)
