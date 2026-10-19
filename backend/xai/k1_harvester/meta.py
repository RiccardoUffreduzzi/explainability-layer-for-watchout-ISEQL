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
from xai.k1_harvester.resource_data import Glossary, PipelineConstants

DetectionMode = Literal["visual", "audio", "multimodal"]
DETECTION_MODES: dict[Condition, DetectionMode] = {"A": "visual", "B": "audio", "C": "multimodal"}

SAMPLING_STRIDE = SourceRef(
    stage=Stage.CODE,
    store="backend/src/service/impl/visual_service_impl.py",
    record_id="frame_count % sampling_rate",
    mode="read",
)
"""``SamplingRate`` is also the stride of the frame sampling."""

VLM_DEFAULTS = SourceRef(
    stage=Stage.CODE,
    store="backend/src/utils/vlm_client.py",
    record_id="VLMClient.__init__: temperature and seed defaults",
    mode="read",
)


class MetaHarvester:
    def __init__(self, glossary: Glossary, constants: PipelineConstants) -> None:
        self.glossary = glossary
        self.constants = constants

    def harvest(self, ctx: HarvestContext) -> ContractMeta:
        analysis = ctx.analysis
        readings = ctx.readings
        return ContractMeta(
            contract_version=cast(ContractVersion, CONTRACT_VERSION),
            analysis_id=analysis.analysis_id,
            source_snapshot=self._snapshot(ctx),
            pipeline_config=self._pipeline_config(ctx),
            glossary_version=f"{self.glossary.label}+relation_vocab@{readings.vocabulary.relation_vocab_updated_at}",
            params_origin=ctx.params.origin,
            sources={
                "glossary_version": SourceRef(
                    stage=Stage.CONFIG, store="AppConfig", record_id="relation_vocab.updated_at", mode="read"
                ),
                "params_origin": ctx.params.origin_source(ctx.rule.ref),
            },
        )

    def _snapshot(self, ctx: HarvestContext) -> SourceSnapshot:
        version = ctx.readings.backend_version()
        if version is None:
            return SourceSnapshot(
                backend_version=None,
                extracted_at=ctx.extracted_at,
                unavailable={
                    "backend_version": Unavailable(
                        reason=Reason.BACKEND_VERSION_NOT_RECORDED,
                        detail=(
                            "backend/src/__init__.py has no __version__ "
                            "and the folder is not a git repository"
                        ),
                    )
                },
            )
        return SourceSnapshot(
            backend_version=version.text,
            extracted_at=ctx.extracted_at,
            sources={"backend_version": version.source},
        )

    def _pipeline_config(self, ctx: HarvestContext) -> PipelineConfig:
        analysis = ctx.analysis
        store = analysis.store
        sources: dict[str, Source] = {}
        unavailable: dict[str, Unavailable] = {}

        def config(record_id: str) -> SourceRef:
            return SourceRef(stage=Stage.CONFIG, store=store, record_id=record_id, mode="read")

        def missing(columns: str) -> Unavailable:
            return Unavailable(reason=Reason.ANALYSIS_RECORD_MISSING, detail=f"{store} has no {columns}")

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
        if fps is None:
            no_fps = Unavailable(reason=Reason.FPS_NOT_RECORDED, detail=f"{store} has no SamplingRate (or 0)")
            for name in ("sampling.source_fps", "sampling.sample_every_n", "sampling.effective_hz"):
                unavailable[name] = no_fps
            sampling = Sampling(source_fps=None, sample_every_n=None, effective_hz=None)
        else:
            sources["sampling.source_fps"] = config("SamplingRate")
            sources["sampling.sample_every_n"] = SAMPLING_STRIDE
            sources["sampling.effective_hz"] = DerivedSource(
                derived_from=["sampling.source_fps", "sampling.sample_every_n"]
            )
            sampling = Sampling(source_fps=fps, sample_every_n=fps, effective_hz=fps / fps)

        if analysis.audio_window is None or analysis.audio_hop is None:
            audio_window = None
            unavailable["audio_window"] = missing("AudioWindow and AudioHop")
        else:
            audio_window = AudioWindow(window_s=analysis.audio_window, hop_s=analysis.audio_hop)
            sources["audio_window"] = config("AudioWindow,AudioHop")

        merge_tolerance_s = ctx.timebase.seconds_of(self.constants.merge_tolerance.samples, fps or 0)
        if merge_tolerance_s is None:
            unavailable["merge_tolerance_s"] = Unavailable(
                reason=Reason.FPS_NOT_RECORDED,
                detail="the merge tolerance is a number of samples: seconds need SamplingRate",
            )
        else:
            sources["merge_tolerance_s"] = SourceRef(
                stage=Stage.CODE, store=self.constants.store, record_id="merge_tolerance", mode="read"
            )

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

    Empty values and ``none`` (WatchOut's default ``AudioQuantization``: no quantization)
    are left out; the value is None when no column has one.
    """
    used = {name: value for name, value in columns.items() if value and value != "none"}
    return (" / ".join(used.values()) if used else None), ",".join(used)
