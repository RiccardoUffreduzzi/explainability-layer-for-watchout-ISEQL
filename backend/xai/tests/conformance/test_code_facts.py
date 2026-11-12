"""Facts of WatchOut's code that K1 cites but does not read at run time.

The merge tolerance, the constant audio confidence and the VLM defaults come from
WatchOut's methods (``CodeFacts``). What stays a citation is checked here with ``ast``:
the code a draft cites exists, and the facts it states about it still hold.
"""

import ast
from pathlib import Path

import pytest

from xai.adapters.watchout.code_facts import WatchOutCodeFacts
from xai.contract.primitives import SourceRef
from xai.k1_harvester.evidence import confidence_source
from xai.k1_harvester.meta import MERGE_TOLERANCE, SAMPLING_STRIDE, VLM_DEFAULTS
from xai.k1_harvester.ports import AudioIntervalRow
from xai.k1_harvester.rule.readers.operator import ENGINE_DEFAULTS
from xai.tests.support import BACKEND_DIR

SRC = BACKEND_DIR / "src"
SERVICE_IMPL = SRC / "service" / "impl"

CLASS_FILES = {
    "VisualServiceImpl": SERVICE_IMPL / "visual_service_impl.py",
    "IntervalServiceImpl": SERVICE_IMPL / "interval_service_impl.py",
    "AudioServiceImpl": SERVICE_IMPL / "audio_service_impl.py",
    "VLMClient": SRC / "utils" / "vlm_client.py",
}
"""The file of each class a code SourceRef names."""

MODULE_FILES = {"compiler.py": SRC / "iseql" / "compiler.py"}


def _method(path: Path, class_name: str, method: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method:
                    return item
    raise AssertionError(f"{path.name}: {class_name}.{method} not found")


def _cited(source: SourceRef) -> tuple[Path, str | None, str]:
    """File, class and function a code ``record_id`` names: ``Class.method...`` or ``file.py/function``."""
    head = source.record_id.split("/", 1)
    if head[0] in MODULE_FILES:
        return MODULE_FILES[head[0]], None, head[1].split(":")[0]
    class_name, rest = source.record_id.split(".", 1)
    return CLASS_FILES[class_name], class_name, rest.split("(")[0].split("/")[0]


@pytest.mark.parametrize(
    "source",
    [SAMPLING_STRIDE, VLM_DEFAULTS, MERGE_TOLERANCE, ENGINE_DEFAULTS],
    ids=lambda s: s.record_id.split(":")[0],
)
def test_the_code_a_draft_cites_exists(source: SourceRef) -> None:
    path, class_name, name = _cited(source)
    if class_name is not None:
        _method(path, class_name, name)
    else:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert any(isinstance(n, ast.FunctionDef) and n.name == name for n in tree.body), (
            f"{path.name}: {name}"
        )


def test_the_constant_confidence_source_names_a_method_of_the_code() -> None:
    row = AudioIntervalRow(interval_id=1, start_frame=0, end_frame=1, audio_class="x", confidence=0.5)
    sources = confidence_source(0.5, "huggingface", row)

    assert sources is not None
    source = sources["confidence"]
    assert isinstance(source, SourceRef)
    path, class_name, name = _cited(source)
    assert class_name is not None
    _method(path, class_name, name)


def test_the_reading_methods_return_what_k1_expects() -> None:
    facts = WatchOutCodeFacts()

    assert isinstance(facts.merge_tolerance_samples(), int)
    assert facts.constant_audio_confidence("huggingface") is not None
    assert facts.constant_audio_confidence("panns") is None
    facts.vlm_defaults()


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
    path, class_name, name = _cited(SAMPLING_STRIDE)
    assert class_name is not None
    function = _method(path, class_name, name)
    strides = [
        ast.unparse(n) for n in ast.walk(function) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod)
    ]
    assert strides == [SAMPLING_STRIDE.record_id.split("/", 1)[1]], (
        "sample_every_n in contract_meta no longer holds"
    )

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
