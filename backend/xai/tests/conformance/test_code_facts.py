"""Facts of WatchOut's code that K1 cannot read at run time.

``resources/pipeline_constants.yaml`` copies them; these tests read the code with
``ast`` and fail, naming the entry to update, when WatchOut changes one of them.
"""

import ast
from pathlib import Path

import pytest

from xai.adapters.resource_files import load_pipeline_constants
from xai.contract.primitives import SourceRef
from xai.k1_harvester.meta import SAMPLING_STRIDE, VLM_DEFAULTS
from xai.k1_harvester.rule.readers.operator import ENGINE_DEFAULTS
from xai.tests.support import BACKEND_DIR

SERVICE_IMPL = BACKEND_DIR / "src" / "service" / "impl"


def _method(path: Path, class_name: str, method: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method:
                    return item
    raise AssertionError(f"{path.name}: {class_name}.{method} not found")


def test_merge_tolerance_is_the_factor_of_the_sampling_rate() -> None:
    constants = load_pipeline_constants()
    path = BACKEND_DIR.parent / constants.merge_tolerance.origin_file
    function = _method(path, "IntervalServiceImpl", "build_visual_and_save")
    assignments = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "merge_threshold" for t in node.targets)
    ]

    assert [ast.unparse(a.value) for a in assignments] == [
        f"{constants.merge_tolerance.samples} * sampling_rate"
    ], "update merge_tolerance in xai/resources/pipeline_constants.yaml"


def test_huggingface_audio_writes_a_constant_confidence() -> None:
    constants = load_pipeline_constants()
    expected = constants.constant_audio_confidence
    path = BACKEND_DIR.parent / expected.origin_file
    function = _method(path, "AudioServiceImpl", "_analyze_huggingface")
    values = [
        value
        for node in ast.walk(function)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values, strict=True)
        if isinstance(key, ast.Constant) and key.value == "confidence"
    ]

    assert values, "update constant_audio_confidence in xai/resources/pipeline_constants.yaml"
    assert all(isinstance(v, ast.Constant) and v.value == expected.value for v in values), (
        "update constant_audio_confidence in xai/resources/pipeline_constants.yaml"
    )


def test_the_analysis_creates_the_vlm_client_with_its_defaults() -> None:
    # K1 reports VLMClient's default temperature and seed: true only while the analysis passes neither.
    tree = ast.parse((SERVICE_IMPL / "analysis_service_impl.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "VLMClient"
    ]

    assert calls
    for call in calls:
        assert not {k.arg for k in call.keywords} & {"temperature", "seed", None}
        assert len(call.args) < 4  # positional temperature or seed


def test_the_visual_pipeline_keeps_one_frame_every_sampling_rate() -> None:
    # K1 reports sample_every_n = SamplingRate: true while the visual pipeline samples with that stride.
    function = _method(BACKEND_DIR.parent / SAMPLING_STRIDE.store, "VisualServiceImpl", "run_pipeline")
    strides = [
        ast.unparse(n) for n in ast.walk(function) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod)
    ]
    assert strides == [SAMPLING_STRIDE.record_id], "sample_every_n in contract_meta no longer holds"

    tree = ast.parse((SERVICE_IMPL / "analysis_service_impl.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run_pipeline"
        and ast.unparse(node.func.value) == "visual"
    ]
    assert calls
    for call in calls:
        keywords = {k.arg: ast.unparse(k.value) for k in call.keywords}
        assert keywords.get("sampling_rate") == "run.sampling_rate", (
            "sample_every_n in contract_meta no longer holds"
        )


@pytest.mark.parametrize("source", [VLM_DEFAULTS, ENGINE_DEFAULTS], ids=lambda s: s.record_id.split(":")[0])
def test_the_code_a_draft_cites_exists(source: SourceRef) -> None:
    # record_id names the function or method before the colon.
    path = BACKEND_DIR.parent / source.store
    name = source.record_id.split(":")[0]
    if "." in name:
        class_name, method = name.split(".")
        _method(path, class_name, method)
    else:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert any(isinstance(n, ast.FunctionDef) and n.name == name for n in tree.body), (
            f"{source.store}: {name}"
        )
