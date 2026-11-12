from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from utils.api_logger import get_logger
from utils.database import commit_with_retry
from utils.gpu_allocator import build_device_map
from service.audio_service import AudioService

log = get_logger(__name__)

SAMPLE_RATE = 32000

AUDIO_PROVIDERS = {"panns": "PANNs", "huggingface": "HuggingFace LALM"}
QUANTIZATION_OPTIONS = ["none", "8bit", "4bit"]

# The HuggingFace audio provider supports a single fixed checkpoint (Qwen2-Audio);
# the model is not user-selectable, mirroring how PANNs pins CNN14.
QWEN2_AUDIO_MODEL_ID = "Qwen/Qwen2-Audio-7B-Instruct"

# --- determinism (same seed block as the evaluation notebooks) ---
SEED = 42

def _set_seed(seed: int = SEED) -> None:
    """Fix RNG seeds so audio inference is reproducible, mirroring the notebooks."""
    import random
    import torch
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

# --- synonym resolution (same as notebook) ---
_RE_KEEP = re.compile(r"[^a-zA-Z0-9_ ]+")

def _stem(word: str) -> str:
    w = word.lower().strip("_.,;:!?")
    for suf in ["ing", "ed", "ly", "s", "es", "ies", "ness", "tion"]:
        if w.endswith(suf) and len(w) > len(suf) + 2:
            return w[: -len(suf)]
    return w

# The audio-event taxonomy (classes + keyword map) is user-configured and
# persisted in the AppConfig store; it is passed in explicitly. There are no
# hardcoded defaults in the backend.

def _build_synonym_lookup(keywords: dict[str, list[str]]) -> dict[str, str]:
    """Build the class synonym map (keyword + stem -> class)."""
    synonyms: dict[str, str] = {}
    for gt, kws in keywords.items():
        for kw in kws:
            synonyms[kw] = gt
            synonyms[_stem(kw)] = gt
    return synonyms


def normalize(text: str, synonyms: dict[str, str]) -> str | None:
    """Resolve a free-text model response to an audio class.

    Resolves naturally: exact whole-string keyword, stemmed whole-string,
    then token-by-token synonym matching.
    """
    clean = _RE_KEEP.sub(" ", text or "").lower()
    clean = " ".join(clean.split())
    if not clean:
        return None
    under = clean.replace(" ", "_")
    if under in synonyms:
        return synonyms[under]
    s_under = _stem(under)
    if s_under in synonyms:
        return synonyms[s_under]
    tokens = [t.strip("_.,;:!?'\"") for t in re.split(r"[_ ,;:\-]+", clean)]
    tokens = [t for t in tokens if len(t) >= 2]
    for token in tokens:
        if token in synonyms:
            return synonyms[token]
        s = _stem(token)
        if s in synonyms:
            return synonyms[s]
    if not tokens:
        return under
    return None

def _sliding_windows(audio: np.ndarray, sr: int, fps: int,
                     window_seconds: float,
                     hop_seconds: float) -> list[tuple[int, int, np.ndarray]]:
    win_s = int(window_seconds * sr)
    hop_s = int(hop_seconds * sr)
    windows = []
    for start in range(0, max(1, len(audio) - win_s + 1), hop_s):
        end = min(start + win_s, len(audio))
        if end - start < sr // 2:
            continue
        sf_ = int(start / sr * fps)
        ef_ = int(end / sr * fps)
        windows.append((sf_, ef_, audio[start:end]))
    return windows


def _merge_predictions(predictions: list[dict], fps: int,
                       hop_seconds: float) -> list[dict]:
    gap = int(hop_seconds * fps)
    merged: dict[str, list] = {}
    for r in predictions:
        merged.setdefault(r["audio_class"], []).append(r)
    out = []
    for sc, evs in merged.items():
        evs.sort(key=lambda x: x["start_frame"])
        cur = evs[0]
        for e in evs[1:]:
            if e["start_frame"] <= cur["end_frame"] + gap:
                cur["end_frame"] = max(cur["end_frame"], e["end_frame"])
                cur["confidence"] = max(cur["confidence"], e["confidence"])
            else:
                out.append(cur)
                cur = e
        out.append(cur)
    return out


def _resolve_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    raise FileNotFoundError("ffmpeg not found on PATH")


def _ffprobe_duration(wav_path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        out = subprocess.check_output(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(wav_path)],
            stderr=subprocess.STDOUT, timeout=30,
        )
        return float(json.loads(out.decode("utf-8"))["format"]["duration"])
    except Exception as e:
        log.warning("ffprobe failed on %s: %s", wav_path, e)
        return 0.0


def extract_wav(video_path: Path, out_wav_path: Path, sample_rate: int = 16000, channels: int = 1,
                log_fn: Optional[Callable[[str], None]] = None) -> Tuple[Path, float]:
    log_fn = log_fn or (lambda msg: log.info(msg))
    video_path, out_wav_path = Path(video_path), Path(out_wav_path)
    out_wav_path.parent.mkdir(parents=True, exist_ok=True)
    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")
    ffmpeg = _resolve_ffmpeg()
    cmd = [ffmpeg, "-y", "-i", str(video_path), "-vn", "-ac", str(channels),
           "-ar", str(sample_rate), "-f", "wav", "-acodec", "pcm_s16le", str(out_wav_path)]
    log_fn(f"ffmpeg: extracting {video_path.name} -> {out_wav_path.name}")
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg failed (rc={e.returncode}): {e.stderr.decode('utf-8', errors='replace')[-1000:]}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"ffmpeg timed out after {e.timeout}s on {video_path}") from e
    duration = _ffprobe_duration(out_wav_path)
    log_fn(f"  -> {duration:.1f}s @ {sample_rate}Hz mono WAV ({out_wav_path.stat().st_size // 1024} KiB)")
    return out_wav_path, duration


def estimate_audio_vram_bytes(quantization: str, safety_factor: float) -> int:
    """Estimate the VRAM the (fixed) Qwen2-Audio model needs (no weight download)."""
    from transformers import Qwen2AudioForConditionalGeneration

    from utils.vram import estimate_hf_vram_bytes
    return estimate_hf_vram_bytes(
        QWEN2_AUDIO_MODEL_ID, Qwen2AudioForConditionalGeneration, quantization, safety_factor
    )


class AudioServiceImpl(AudioService):
    @staticmethod
    def constant_confidence(provider: str) -> float | None:
        """Confidence stored for every interval of a provider that gives no score.

        Qwen2-Audio answers with a class name only, so its intervals
        get 1.0; panns stores the model's own score (None here).
        """
        return 1.0 if provider == "huggingface" else None

    def __init__(self, audio_provider: str, quantization: str,
                 audio_window: float, audio_hop: float,
                 classes: list[str], keywords: dict[str, list[str]],
                 max_memory_fraction: float,
                 device: str = "cpu", devices: Optional[List[str]] = None,
                 allow_cpu_offload: bool = False):
        if not classes:
            raise ValueError("audio taxonomy classes must not be empty")
        if not keywords:
            raise ValueError("audio taxonomy keywords must not be empty")
        self.audio_provider = audio_provider
        # Both providers ship a single fixed checkpoint; the model is not
        # user-selectable.
        self.audio_model = "CNN14" if audio_provider == "panns" else QWEN2_AUDIO_MODEL_ID
        self.quantization = quantization
        self.device = device
        # Full leased device set (for sharding a model that exceeds one GPU).
        self.devices = list(devices) if devices else ([device] if device != "cpu" else ["cpu"])
        self.max_memory_fraction = max_memory_fraction
        self.allow_cpu_offload = allow_cpu_offload
        self.window_seconds = audio_window
        self.hop_seconds = audio_hop
        self.classes = list(classes)
        self.keywords = {k: list(v) for k, v in keywords.items()}
        self._synonyms = _build_synonym_lookup(self.keywords)

    def run_pipeline(self, video_path: Path, conn: sqlite3.Connection, out_dir: Path,
                     fps: int = 24, analysis_id: str = "",
                     log_fn: Optional[Callable[[str], None]] = None) -> dict:
        log_fn = log_fn or (lambda msg: log.info(msg))
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        _set_seed()

        wav_path = out_dir / (Path(video_path).stem + ".16k.wav")
        wav_path, duration = extract_wav(video_path, wav_path, log_fn=log_fn)

        log_fn(f">>> Audio provider: {self.audio_provider}")
        try:
            results = self._analyze_audio(str(wav_path), fps, log_fn)
        except Exception as e:
            log_fn(f"audio classification failed: {e}")
            results = []

        cur = conn.cursor()
        count = 0
        for sc, sf, ef, cf in results:
            csc = normalize(sc, self._synonyms)
            if csc is not None:
                cur.execute(
                    "INSERT INTO AudioPerInterval (AnalysisID, AudioClass, StartFrame, EndFrame, Confidence) VALUES (?, ?, ?, ?, ?)",
                    (analysis_id, csc, sf, ef, cf),
                )
                count += 1

        commit_with_retry(conn)
        log_fn(f"persisted {count} AudioPerInterval rows from {self.audio_provider}")

        return {"wav_path": str(wav_path), "duration_s": float(duration),
                "n_audio_events": len(results), "audio_provider": self.audio_provider}

    def _analyze_audio(self, audio_path: str, fps: int, log_fn) -> list:
        if self.audio_provider == "panns":
            return self._analyze_panns(audio_path, fps, log_fn)
        elif self.audio_provider == "huggingface":
            return self._analyze_huggingface(audio_path, fps, log_fn)
        return []

    def _analyze_panns(self, audio_path: str, fps: int, log_fn) -> list:
        import soundfile as sf
        import torch
        import scipy.signal
        from panns_inference import AudioTagging

        audio_16k, _ = sf.read(audio_path, dtype="float32")
        if audio_16k.ndim > 1:
            audio_16k = audio_16k.mean(axis=-1)
        if audio_16k.size < 16000:
            log_fn("audio too short, skipping")
            return []

        # Resample 16kHz → 32kHz (PANNs native rate)
        n_out = int(round(len(audio_16k) * SAMPLE_RATE / 16000))
        audio_32k = scipy.signal.resample(audio_16k.astype(np.float32), n_out).astype(np.float32)

        # Load PANNs model once
        classifier = AudioTagging(device=self.device)

        def _infer(audio):
            audio_list = audio.flatten().tolist() if isinstance(audio, np.ndarray) else audio
            audio_t = torch.tensor(audio_list, dtype=torch.float32).unsqueeze(0)
            if classifier.device != "cpu":
                audio_t = audio_t.to(classifier.device)
            with torch.no_grad():
                classifier.model.eval()
                out = classifier.model(audio_t, None)
            return out["clipwise_output"][0].detach().cpu().tolist()

        labels_list = list(classifier.labels)
        all_results = []

        for sf_, ef_, clip in _sliding_windows(audio_32k, SAMPLE_RATE, fps,
                                               self.window_seconds, self.hop_seconds):
            if clip.size < SAMPLE_RATE // 2:
                continue
            # Pad to 10s (320k samples at 32kHz) - PANNs trained on 10s AudioSet clips
            pad_len = max(0, 10 * SAMPLE_RATE - clip.size)
            if pad_len > 0:
                clip = np.concatenate([clip, np.zeros(pad_len, dtype=np.float32)])
            try:
                probs = _infer(clip)
                if isinstance(probs, list) and probs and isinstance(probs[0], list):
                    probs = probs[0]
                scores = [(l, float(p)) for l, p in zip(labels_list, probs)]
                scores.sort(key=lambda x: -x[1])
                top = scores[:1]
            except Exception as e:
                log_fn(f"  window classify failed: {e}")
                top = []
            for label, conf in top:
                all_results.append({"audio_class": label, "start_frame": sf_,
                                    "end_frame": ef_, "confidence": conf})

        out = _merge_predictions(all_results, fps, self.hop_seconds)
        log_fn(f"PANNs: {len(out)} audio events detected")
        return [(r["audio_class"], r["start_frame"], r["end_frame"], r["confidence"]) for r in out]

    def _analyze_huggingface(self, audio_path: str, fps: int, log_fn) -> list:
        import torch
        from transformers import Qwen2AudioForConditionalGeneration, AutoProcessor
        import soundfile as sf

        log_fn(f"HuggingFace LALM: loading model...")
        model_id = self.audio_model
        device_or_map, max_memory = build_device_map(
            self.devices, self.max_memory_fraction, self.allow_cpu_offload
        )
        load_kwargs = {"pretrained_model_name_or_path": model_id}
        if device_or_map:
            load_kwargs["device_map"] = device_or_map
            if max_memory:
                load_kwargs["max_memory"] = max_memory
        if self.quantization == "4bit":
            # bitsandbytes is CUDA-only; import lazily so non-CUDA (e.g. macOS)
            # and full-precision paths do not require it at install time.
            from transformers import BitsAndBytesConfig
            load_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16, llm_int8_enable_fp32_cpu_offload=True)
        elif self.quantization == "8bit":
            from transformers import BitsAndBytesConfig
            load_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True, llm_int8_enable_fp32_cpu_offload=True)
        else:
            log_fn("WARNING: full-precision is slow. Use 4bit for speed.")
        model = Qwen2AudioForConditionalGeneration.from_pretrained(**load_kwargs)
        processor = AutoProcessor.from_pretrained(model_id)

        waveform, sr = sf.read(audio_path, dtype="float32")
        if waveform.ndim > 1:
            waveform = waveform.mean(axis=-1)
        log_fn(f"Audio duration: {len(waveform)/sr:.1f}s")

        all_results, window_idx = [], 0
        import os, tempfile

        for sf_, ef_, clip in _sliding_windows(waveform, sr, fps,
                                                self.window_seconds, self.hop_seconds):
            path = os.path.join(tempfile.gettempdir(), f"qwen2_window_{window_idx}.wav")
            sf.write(path, clip, sr, subtype="PCM_16")

            prompt = (
                "Analyze the audio clip. What is the most prominent sound?\n"
                "Choose exactly one category from: " + ", ".join(self.classes) + "\n"
                "\n"
                "If NONE of the above categories apply, output: none()\n"
                "\n"
                "Do NOT output any other text."
            )

            conversation = [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {"role": "user", "content": [{"type": "audio", "audio_url": path}, {"type": "text", "text": prompt}]},
            ]
            text = processor.apply_chat_template(conversation, add_generation_prompt=True, tokenize=False)
            inputs = processor(text=text, audio=clip, return_tensors="pt", padding=True, sampling_rate=sr).to(model.device)
            with torch.no_grad():
                ids = model.generate(**inputs, max_new_tokens=32, do_sample=False)
            response = processor.batch_decode(ids[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)[0]

            resp = response.strip().rstrip(". ").replace(" ", "_")
            if resp and resp not in ('none', 'none()'):
                csc = normalize(resp, self._synonyms)
                if csc:
                    all_results.append({"audio_class": csc, "start_frame": sf_, "end_frame": ef_,
                                        "confidence": self.constant_confidence("huggingface")})
                    log_fn(f"  Window {window_idx}: {csc}")

            window_idx += 1
            if window_idx >= 30:
                break
            try:
                os.unlink(path)
            except OSError:
                pass

        out = _merge_predictions(all_results, fps, self.hop_seconds)
        log_fn(f"HuggingFace LALM: {len(out)} audio events detected")
        return [(r["audio_class"], r["start_frame"], r["end_frame"], r["confidence"]) for r in out]







