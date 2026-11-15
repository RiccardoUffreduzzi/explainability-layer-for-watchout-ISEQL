from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import cv2
from fastapi import File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse

from models.analysis import (
    VALID_SAMPLING_RATES,
    AnalysisDetectRequest,
    AnalysisStage,
    AnalysisStartResponse,
    Condition,
)
from utils.config import VALID_CONDITIONS, Config
from utils.api_logger import get_logger
from utils.sse import drain_queue_into_sse
from utils.vlm_client import VLMClient

log = get_logger(__name__)


def _parse_json_field(raw: str | None) -> dict | None:
    """Parse an optional JSON form field into a dict (None when empty/absent)."""
    if not raw or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"invalid JSON field: {e}")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="expected a JSON object")
    return parsed


def _parse_audio_classes(raw: dict | None) -> list[str] | None:
    """Validate the audio classes payload ({"classes": [...]})."""
    if raw is None:
        return None
    classes = raw.get("classes")
    if not isinstance(classes, list) or not all(isinstance(c, str) and c for c in classes):
        raise HTTPException(status_code=400, detail="audio classes must be a list of non-empty strings")
    return classes


def _parse_audio_keywords(raw: dict | None) -> dict[str, list[str]] | None:
    """Validate the audio keywords payload ({"keywords": {class: [kw, ...]}})."""
    if raw is None:
        return None
    keywords = raw.get("keywords")
    if not isinstance(keywords, dict):
        raise HTTPException(status_code=400, detail="audio keywords must be an object mapping class -> keywords")
    out: dict[str, list[str]] = {}
    for cls, kws in keywords.items():
        if not isinstance(cls, str) or not cls:
            raise HTTPException(status_code=400, detail="audio keyword class must be a non-empty string")
        if not isinstance(kws, list) or not all(isinstance(k, str) and k for k in kws):
            raise HTTPException(status_code=400, detail=f"audio keywords for '{cls}' must be a list of strings")
        out[cls] = list(kws)
    return out


class AnalysisStartController:
    """Start a new analysis by uploading a video."""
    def __init__(self, analysis_service) -> None:
        self._service = analysis_service

    async def on_post(
        self,
        video: UploadFile = File(...),
        condition: str = Form("A"),
        vlm_provider: str = Form(None),
        model: str = Form(""),
        grid_rows: int = Form(2),
        grid_cols: int = Form(4),
        sampling_rate: float = Form(1.0),
        vlm_delay: float = Form(0.0),
        max_retries: int = Form(3),
        embed_provider: str = Form(None),
        embed_model: str = Form(""),
        memory_n: int = Form(3),
        memory_top_k: int = Form(5),
        audio_provider: str = Form("panns"),
        audio_model: str = Form("CNN14"),
        audio_quantization: str = Form("none"),
        audio_window: float = Form(2.5),
        audio_hop: float = Form(1.25),
        audio_classes: str = Form(None),
        audio_keywords: str = Form(None),
    ) -> AnalysisStartResponse:
        cfg = Config.get()
        available = Config.get_available_providers()

        if condition not in VALID_CONDITIONS:
            raise HTTPException(status_code=400, detail=f"unknown condition '{condition}'; expected A | B | C")
        if sampling_rate not in VALID_SAMPLING_RATES:
            raise HTTPException(
                status_code=400,
                detail="sampling_rate must be one of: 0.5, 1, 2",
            )
        if vlm_provider is None:
            vlm_provider = available[0] if available else "ollama"
        if embed_provider is None:
            embed_provider = "huggingface"
        if not embed_model:
            embed_model = "google/siglip-base-patch16-224"
        if condition in ("A", "C") and vlm_provider not in available:
            raise HTTPException(status_code=400, detail=f"Provider '{vlm_provider}' not available")

        upload_dir = Path(cfg.data.upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(video.filename or "upload.mp4").name
        target_path = upload_dir / f"{uuid.uuid4().hex[:12]}_{safe_name}"
        with target_path.open("wb") as f:
            shutil.copyfileobj(video.file, f)
        log.info("Stored upload as %s (condition=%s)", target_path, condition)

        # Auto-detect the source frame rate.  Visual sampling derives its frame
        # step from this value and sampling_rate; all timestamp/audio logic
        # keeps using the source frame rate itself.
        frame_rate = 24.0
        try:
            probe = subprocess.check_output(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=avg_frame_rate,r_frame_rate",
                 "-of", "json", str(target_path)],
                timeout=10, stderr=subprocess.PIPE,
            )
            info = json.loads(probe)
            stream = info["streams"][0]
            for key in ("avg_frame_rate", "r_frame_rate"):
                fps_str = stream.get(key, "")
                if fps_str and "/" in fps_str:
                    num, den = fps_str.split("/")
                    fps = float(num) / float(den) if float(den) else 0
                    if fps > 0:
                        frame_rate = fps
                        log.info("Detected video frame rate: %.3f (from %s=%s)", frame_rate, key, fps_str)
                        break
            else:
                log.info("Could not parse frame rate, using default 24")
        except Exception:
            cap = cv2.VideoCapture(str(target_path))
            try:
                detected_fps = float(cap.get(cv2.CAP_PROP_FPS)) if cap.isOpened() else 0.0
                if detected_fps > 0:
                    frame_rate = detected_fps
                    log.info("Detected video frame rate with OpenCV fallback: %.3f", frame_rate)
                else:
                    log.info("Could not detect frame rate, using default 24")
            finally:
                cap.release()

        run = self._service.start_analysis(
            video_path=target_path,
            video_filename=safe_name,
            condition=condition,
            vlm_provider=vlm_provider,
            model=model,
            grid_rows=grid_rows,
            grid_cols=grid_cols,
            frame_rate=frame_rate,
            sampling_rate=sampling_rate,
            vlm_delay=vlm_delay,
            max_retries=max_retries,
            embed_provider=embed_provider,
            embed_model=embed_model,
            memory_n=int(memory_n),
            memory_top_k=int(memory_top_k),
            audio_provider=audio_provider,
            audio_model=audio_model,
            audio_quantization=audio_quantization,
            audio_window=audio_window,
            audio_hop=audio_hop,
            audio_classes=_parse_audio_classes(_parse_json_field(audio_classes)),
            audio_keywords=_parse_audio_keywords(_parse_json_field(audio_keywords)),
        )
        return AnalysisStartResponse(
            analysis_id=run.id,
            condition=Condition(condition),
            stage=AnalysisStage.QUEUED,
            frame_rate=frame_rate,
            sampling_rate=sampling_rate,
        )


class AnalysisLogsController:
    def __init__(self, analysis_service) -> None:
        self._service = analysis_service

    async def on_get(self, analysis_id: str) -> StreamingResponse:
        run = self._service.get_run(analysis_id)
        return StreamingResponse(
            drain_queue_into_sse(run.log_queue),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


class AnalysisStatusController:
    def __init__(self, analysis_service) -> None:
        self._service = analysis_service

    async def on_get(self, analysis_id: str) -> dict:
        return self._service.get_status(analysis_id)


class AnalysisListController:
    def __init__(self, analysis_service) -> None:
        self._service = analysis_service

    async def on_get(self) -> list[dict]:
        return self._service.list_analyses()


class AnalysisDetectController:
    def __init__(self, analysis_service) -> None:
        self._service = analysis_service

    async def on_get(self, analysis_id: str, event_type: str) -> StreamingResponse:
        raise HTTPException(status_code=400, detail="GET /detect is deprecated. Use POST.")

    async def on_post(self, analysis_id: str, request: AnalysisDetectRequest) -> dict:
        run = self._service.get_run(analysis_id)
        return self._service.detect_event(
            analysis_id=analysis_id,
            event_type=request.event_type,
            condition=run.condition,
            deltas=request.deltas,
            unit=request.unit,
        )


class AnalysisVideoController:
    """Stream the uploaded video for an analysis (supports HTTP Range for seeking)."""
    def __init__(self, analysis_service) -> None:
        self._service = analysis_service

    async def on_get(self, analysis_id: str) -> FileResponse:
        run = self._service.get_run(analysis_id)
        path = Path(run.video_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="video file not found for this analysis")
        return FileResponse(path, media_type="video/mp4", filename=path.name)


class AnalysisThumbnailController:
    """Return one requested frame from an analysis video as a JPEG thumbnail."""
    def __init__(self, analysis_service) -> None:
        self._service = analysis_service

    async def on_get(self, analysis_id: str, frame: int = Query(..., ge=0)) -> Response:
        run = self._service.get_run(analysis_id)
        path = Path(run.video_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="video file not found for this analysis")

        cap = cv2.VideoCapture(str(path))
        try:
            if not cap.isOpened():
                raise HTTPException(status_code=422, detail="video file could not be opened")

            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if frame_count > 0 and frame >= frame_count:
                raise HTTPException(status_code=416, detail="frame is outside the video range")

            cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
            ok, image = cap.read()
            if not ok or image is None:
                raise HTTPException(status_code=422, detail="could not extract requested video frame")

            height, width = image.shape[:2]
            if width <= 0 or height <= 0:
                raise HTTPException(status_code=422, detail="extracted video frame has invalid dimensions")
            thumbnail_width = 360
            thumbnail_height = max(1, round(height * thumbnail_width / width))
            thumbnail = cv2.resize(image, (thumbnail_width, thumbnail_height), interpolation=cv2.INTER_AREA)
            encoded, jpeg = cv2.imencode(".jpg", thumbnail)
            if not encoded:
                raise HTTPException(status_code=500, detail="could not encode thumbnail")
            return Response(
                content=jpeg.tobytes(),
                media_type="image/jpeg",
                headers={"Cache-Control": "private, max-age=3600"},
            )
        finally:
            cap.release()


class AnalysisStopController:
    def __init__(self, analysis_service) -> None:
        self._service = analysis_service

    async def on_post(self, analysis_id: str) -> dict:
        self._service.stop_analysis(analysis_id)
        return {"status": "stopped"}


class AnalysisDeleteController:
    def __init__(self, analysis_service) -> None:
        self._service = analysis_service

    async def on_post(self, analysis_id: str) -> dict:
        self._service.delete_analysis(analysis_id)
        return {"status": "deleted"}


class VLMModelsController:
    async def on_get(self, provider: str = "ollama") -> dict:
        available = Config.get_available_providers()
        if provider not in available:
            raise HTTPException(status_code=400, detail=f"Provider '{provider}' not available")
        try:
            # Model listing is only meaningful for ollama (server-side tags);
            # a client without an explicit model cannot be constructed.
            if provider != "ollama":
                return {"models": []}
            client = VLMClient(provider=provider, model="_list_models_")
            return {"models": client.list_models()}
        except Exception as e:
            log.warning("Cannot list models for %s: %s", provider, e)
            return {"models": [], "error": str(e)}
