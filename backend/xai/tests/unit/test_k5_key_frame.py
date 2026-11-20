"""The key frame in Report 1: a sentence of the LLM and, below it, the image with a caption of the
system, at the end of what was observed; the LLM never sees the image nor the caption (A2-bis)."""

import hashlib
from pathlib import Path
from typing import Any

from xai.adapters.report_resources import load_sentences
from xai.contract import ContractDraft
from xai.contract.report import Section, dump_report, load_report
from xai.k1_harvester.output import AnalysisFolder
from xai.k2.stage import K2Stage
from xai.k4_planner.stage import K4Stage
from xai.pipeline.paths import k2_path, k4_path, k5_path
from xai.reporting.files import ReportFiles, write_report
from xai.reporting.renderer import markdown
from xai.reporting.writer import WrittenReport
from xai.tests.k5_support import ScriptedModel, StillFrames, hand_text, pair_of, writer
from xai.tests.support import EXAMPLES_DIR, from_json_data, load_example

HANDOFF = "handoff_s21_A"
EV = "ev_beffcb6f2a6e"
CAPTION = load_sentences("report1").figure
OBSERVED = "What was observed"
SENTENCE = "WatchOut shows this detection with its key frame, frame 108, at 0:04.5."


def _sections(written: WrittenReport) -> dict[str, Section]:
    return {section.title: section for section in written.report.sections}


def test_what_was_observed_shows_the_key_frame_with_the_caption_of_the_system() -> None:
    frames = StillFrames()

    written = writer(ScriptedModel([hand_text(HANDOFF)]), frames=frames).write(*pair_of(HANDOFF))

    figure = _sections(written)[OBSERVED].figure
    assert figure is not None
    assert (figure.keyframe_id, figure.frame_index, figure.status) == ("kf_108", 108, "shown")
    assert figure.file == f"{EV}.jpg" and figure.ref == "#/event/key_frame"
    assert figure.sha256 == hashlib.sha256(frames.jpeg).hexdigest()
    assert figure.caption == CAPTION["shown"].replace("<time>", "0:04.5").replace("<frame>", "108")
    assert written.image == frames.jpeg
    assert written.report.report_meta.key_frame_images is True
    assert figure.caption == "Key frame at 0:04.5 (frame 108)."
    assert all(s.figure is None for s in written.report.sections if s.title != OBSERVED)


def test_the_markdown_puts_the_image_and_its_caption_after_the_text_of_the_section() -> None:
    written = writer(ScriptedModel([hand_text(HANDOFF)]), frames=StillFrames()).write(*pair_of(HANDOFF))

    text = written.markdown
    image = f"![Key frame 108]({EV}.jpg)"
    figure = _sections(written)[OBSERVED].figure
    assert figure is not None
    assert image in text
    assert text.index(f"## {OBSERVED}") < text.index(SENTENCE) < text.index(image)
    assert text.index(image) < text.index("## Why it was flagged")
    assert f"*{figure.caption}*" in text
    assert markdown(written.report) == text


def test_the_llm_sees_neither_the_image_nor_the_caption() -> None:
    llm = ScriptedModel([hand_text(HANDOFF)])

    written = writer(llm, frames=StillFrames()).write(*pair_of(HANDOFF))

    prompt = llm.prompts[0]
    figure = _sections(written)[OBSERVED].figure
    assert figure is not None and figure.caption not in prompt
    assert "Key frame at" not in prompt and ".jpg" not in prompt and "video_path" not in prompt
    assert '"kf_108.at": "0:04.5"' in prompt and '"kf_108.frame": "108"' in prompt


def test_the_sentence_of_the_key_frame_is_in_the_text_of_what_was_observed() -> None:
    written = writer(ScriptedModel([hand_text(HANDOFF)]), frames=StillFrames()).write(*pair_of(HANDOFF))

    last = _sections(written)[OBSERVED].sentences[-1]
    assert last.step_ids == ["s_key_frame"]
    assert last.text == SENTENCE
    assert [value.name for value in last.values] == ["kf_108.frame", "kf_108.at"]


def test_without_the_image_the_caption_says_why() -> None:
    missing = "video file not found for this analysis"

    written = writer(ScriptedModel([hand_text(HANDOFF)]), frames=StillFrames(missing=missing)).write(
        *pair_of(HANDOFF)
    )

    figure = _sections(written)[OBSERVED].figure
    assert figure is not None and figure.status == "not_available"
    assert figure.file is None and figure.sha256 is None and written.image is None
    assert figure.caption == CAPTION["not_available"].replace("<frame>", "108").replace("<reason>", missing)
    assert "![" not in written.markdown and f"*{figure.caption}*" in written.markdown


def test_without_the_time_of_the_key_frame_the_caption_names_only_the_frame() -> None:
    def no_time(data: dict[str, Any]) -> None:
        data["event"]["key_frame"]["t_s"] = None
        data["event"]["key_frame"]["unavailable"] = {"t_s": {"reason": "fps_not_recorded", "detail": "x"}}

    written = writer(ScriptedModel([hand_text(HANDOFF)]), frames=StillFrames()).write(
        *pair_of(HANDOFF, no_time)
    )

    figure = _sections(written)[OBSERVED].figure
    assert figure is not None and figure.caption == CAPTION["shown_without_time"].replace("<frame>", "108")
    assert figure.caption == "Key frame 108."


def test_with_the_images_turned_off_the_report_has_no_figure() -> None:
    written = writer(ScriptedModel([hand_text(HANDOFF)])).write(*pair_of(HANDOFF))

    assert all(section.figure is None for section in written.report.sections)
    assert written.image is None and written.report.report_meta.key_frame_images is False


def test_a_draft_without_key_frame_gives_a_report_without_figure() -> None:
    def no_key_frame(data: dict[str, Any]) -> None:
        data["event"]["key_frame"] = None
        data["event"].setdefault("unavailable", {})["key_frame"] = {
            "reason": "keyframe_not_shown",
            "detail": "x",
        }

    frames = StillFrames()
    text = "\n".join(line for line in hand_text(HANDOFF).split("\n") if "[s_key_frame]" not in line)
    plan, document = pair_of(HANDOFF, no_key_frame)
    written = writer(ScriptedModel([text]), frames=frames).write(plan, document)

    assert all(section.figure is None for section in written.report.sections)
    assert frames.asked == []
    assert "s_key_frame" not in [step.step_id for step in plan.steps]


def test_the_report_with_a_figure_survives_a_round_trip() -> None:
    written = writer(ScriptedModel([hand_text(HANDOFF)]), frames=StillFrames()).write(*pair_of(HANDOFF))

    assert load_report(dump_report(written.report)) == written.report


# ----------------------------------------------------------------------------- files


def _planned(root: Path) -> Path:
    draft = from_json_data(ContractDraft, load_example(EXAMPLES_DIR / f"{HANDOFF}.bozza.json"))
    draft_path = AnalysisFolder(root, "an_test").draft_path(draft.event.label, draft.event.event_id)
    K2Stage().process(draft, draft_path)
    K4Stage().process(draft, draft_path)
    return draft_path


def _write(draft_path: Path, frames: StillFrames | None, answers: int = 1) -> str:
    llm = ScriptedModel([hand_text(HANDOFF)] * answers)
    return write_report(
        writer(llm, frames=frames), k4_path(draft_path), k2_path(draft_path), k5_path(draft_path)
    )


def test_the_image_is_written_beside_the_report(tmp_path: Path) -> None:
    draft_path = _planned(tmp_path)
    frames = StillFrames()

    assert _write(draft_path, frames) == "written"

    files = ReportFiles.of(k5_path(draft_path))
    assert files.image.name == f"{EV}.jpg" and files.image.read_bytes() == frames.jpeg
    assert not list(files.json.parent.glob("*.tmp"))


def test_a_report_whose_image_is_gone_is_written_again(tmp_path: Path) -> None:
    draft_path = _planned(tmp_path)
    _write(draft_path, StillFrames())
    files = ReportFiles.of(k5_path(draft_path))

    assert _write(draft_path, StillFrames()) == "current"
    files.image.unlink()
    assert _write(draft_path, StillFrames()) == "written"
    assert files.image.is_file()


def test_turning_the_images_off_writes_the_report_again_without_image(tmp_path: Path) -> None:
    draft_path = _planned(tmp_path)
    _write(draft_path, StillFrames())
    files = ReportFiles.of(k5_path(draft_path))

    assert _write(draft_path, None) == "written"
    assert not files.image.exists()
    assert "![" not in files.markdown.read_text(encoding="utf-8")
