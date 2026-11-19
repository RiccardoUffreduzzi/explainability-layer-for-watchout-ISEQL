"""``contract_meta``: which state of WatchOut was read, with which configuration."""

from typing import Literal, cast

from xai.contract.model import (
    CONTRACT_VERSION,
    AudioWindow,
    Condition,
    ContractMeta,
    ContractVersion,
    Determinism,
    PipelineConfig,
    Sampling,
    SourceSnapshot,
)
from xai.contract.primitives import DerivedSource, RequestSource, Source, SourceRef, Stage, Unavailable
from xai.contract.reasons import Reason
from xai.k1_harvester.context import HarvestContext
from xai.k1_harvester.resource_data import Glossary

DetectionMode = Literal["visual", "audio", "multimodal"]
DETECTION_MODES: dict[Condition, DetectionMode] = {"A": "visual", "B": "audio", "C": "multimodal"}

SAMPLING_STRIDE = SourceRef(
    stage=Stage.CODE,
    record_id="VisualServiceImpl.run_pipeline/frame_count % frame_step",
    mode="read",
)
"""The visual pipeline keeps one frame every ``frame_step_for(FrameRate, SamplingRate)``."""

VLM_DEFAULTS = SourceRef(stage=Stage.CODE, record_id="VLMClient.generation_defaults()", mode="read")

MERGE_TOLERANCE = SourceRef(stage=Stage.CODE, record_id="analysis.py/merge_gap_frames_for", mode="read")
"""The analysis passes ``merge_gap_frames_for(FrameRate)`` to the interval merge."""


class MetaHarvester:
    def __init__(self, glossary: Glossary) -> None:
        self.glossary = glossary

    def harvest(self, ctx: HarvestContext) -> ContractMeta:
        analysis = ctx.analysis
        readings = ctx.readings
        return ContractMeta(
            contract_version=cast(ContractVersion, CONTRACT_VERSION),
            analysis_id=analysis.analysis_id,
            source_snapshot=self._snapshot(ctx),
            pipeline_config=self._pipeline_config(ctx),
            glossary_version=(
                f"{self.glossary.label}"
                f"+relation_vocab@{readings.vocabulary.relation_vocab_updated_at}"
                f"+audio_taxonomy@{readings.vocabulary.audio_taxonomy_updated_at}"
            ),
            params_origin=ctx.params.origin,
            sources={
                "glossary_version": SourceRef(
                    stage=Stage.CONFIG,
                    record_id="AppConfig/relation_vocab.updated_at, audio_taxonomy.updated_at",
                    mode="read",
                ),
                "params_origin": ctx.params.origin_source(ctx.rule.ref),
            },
        )

    @staticmethod
    def _snapshot(ctx: HarvestContext) -> SourceSnapshot:
        return SourceSnapshot(extracted_at=ctx.extracted_at)

    def _pipeline_config(self, ctx: HarvestContext) -> PipelineConfig:
        analysis = ctx.analysis
        record = analysis.record
        sources: dict[str, Source] = {}
        unavailable: dict[str, Unavailable] = {}

        def config(record_id: str) -> SourceRef:
            return SourceRef(stage=Stage.CONFIG, record_id=f"{record}/{record_id}", mode="read")

        def missing(columns: str) -> Unavailable:
            return Unavailable(reason=Reason.ANALYSIS_RECORD_MISSING, detail=f"{record} has no {columns}")

        vlm_backend, vlm_columns = _joined(VLMProvider=analysis.vlm_provider, Model=analysis.model)
        if vlm_backend is None:
            unavailable["vlm_backend"] = missing("VLMProvider and Model")
        else:
            sources["vlm_backend"] = config(vlm_columns)

        audio_backend, audio_columns = _joined(
            AudioProvider=analysis.audio_provider,
            AudioModel=analysis.audio_model,
            AudioQuantization=analysis.audio_quantization,
        )
        if audio_backend is None:
            unavailable["audio_backend"] = missing("AudioProvider, AudioModel and AudioQuantization")
        else:
            sources["audio_backend"] = config(audio_columns)

        fps = analysis.fps
        facts = ctx.readings.facts
        if fps is None or analysis.sampling_hz is None:
            column = analysis.fps_column if fps is None else "SamplingRate"
            no_fps = Unavailable(reason=Reason.FPS_NOT_RECORDED, detail=f"{record} has no {column} (or 0)")
            for name in ("sampling.source_fps", "sampling.sample_every_n", "sampling.effective_hz"):
                unavailable[name] = no_fps
            sampling = Sampling(source_fps=None, sample_every_n=None, effective_hz=None)
        else:
            step = facts.frame_step(fps, analysis.sampling_hz)
            sources["sampling.source_fps"] = config(analysis.fps_column)
            sources["sampling.sample_every_n"] = SAMPLING_STRIDE
            sources["sampling.effective_hz"] = DerivedSource(
                derived_from=["sampling.source_fps", "sampling.sample_every_n"]
            )
            sampling = Sampling(source_fps=fps, sample_every_n=step, effective_hz=round(fps / step, 6))

        if analysis.audio_window is None or analysis.audio_hop is None:
            audio_window = None
            unavailable["audio_window"] = missing("AudioWindow and AudioHop")
        else:
            audio_window = AudioWindow(window_s=analysis.audio_window, hop_s=analysis.audio_hop)
            sources["audio_window"] = config("AudioWindow,AudioHop")

        merge_tolerance_s = None if fps is None else ctx.timebase.seconds_of(facts.merge_gap_frames(fps), 1)
        if merge_tolerance_s is None:
            unavailable["merge_tolerance_s"] = Unavailable(
                reason=Reason.FPS_NOT_RECORDED,
                detail="the merge tolerance is a number of video frames: seconds need FrameRate",
            )
        else:
            sources["merge_tolerance_s"] = MERGE_TOLERANCE

        defaults = ctx.readings.vlm_defaults()
        sources["determinism"] = VLM_DEFAULTS
        sources["detection_mode"] = RequestSource(from_request="condition", value=ctx.condition)
        return PipelineConfig(
            vlm_backend=vlm_backend,
            audio_backend=audio_backend,
            sampling=sampling,
            audio_window=audio_window,
            merge_tolerance_s=merge_tolerance_s,
            determinism=Determinism(temperature=defaults.temperature, seed=defaults.seed),
            detection_mode=DETECTION_MODES[ctx.condition],
            sources=sources,
            unavailable=unavailable or None,
        )


def _joined(**columns: str | None) -> tuple[str | None, str]:
    """The values of the columns joined with `` / ``, and the names of the columns used.

    Empty values and ``none`` (default ``AudioQuantization``: no quantization)
    are left out; the value is None when no column has one.
    """
    used = {name: value for name, value in columns.items() if value and value != "none"}
    return (" / ".join(used.values()) if used else None), ",".join(used)
