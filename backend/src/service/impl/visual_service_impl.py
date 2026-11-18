from __future__ import annotations

import base64
import io
import json
import re
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, Optional

import cv2
import numpy as np
from PIL import Image
from service.impl.interval_service_impl import IntervalServiceImpl

from utils.api_logger import get_logger
from utils.object_memory import ObjectMemory
from utils.vlm_client import VLMClient
from service.visual_service import VisualService

log = get_logger(__name__)

try:
    from json_repair import loads as _json_repair_loads
except ImportError:  # pragma: no cover - stdlib fallback keeps the backend runnable without it
    _json_repair_loads = None

def draw_grid_on_image(image_pil: Image.Image, rows: int = 2, cols: int = 4) -> Image.Image:
    image_cv = cv2.cvtColor(np.array(image_pil), cv2.COLOR_RGB2BGR)
    h, w, _ = image_cv.shape
    block_width = w // cols
    block_height = h // rows
    for i in range(1, cols):
        cv2.line(image_cv, (i * block_width, 0), (i * block_width, h), (0, 0, 255), 2)
    for i in range(1, rows):
        cv2.line(image_cv, (0, i * block_height), (w, i * block_height), (0, 0, 255), 2)
    for row in range(rows):
        for col in range(cols):
            block_num = row * cols + col + 1
            text_pos = (col * block_width + 20, row * block_height + 60)
            cv2.putText(
                image_cv, str(block_num), text_pos,
                cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 0), 3,
            )
    return Image.fromarray(cv2.cvtColor(image_cv, cv2.COLOR_BGR2RGB))

@dataclass
class VlmResponse:
    text: str = ""

_last_call_time: dict[str, float] = {}

def _is_rate_limit(e: Exception) -> bool:
    msg = str(e).lower()
    return "429" in msg or "rate limit" in msg or "rate_limited" in msg

def _is_transient_network(e: Exception) -> bool:
    """Transient network failures (timeout / connection dropped) that should be retried
    until connectivity returns, so a frame is never left partial or corrupted."""
    names = {c.__name__ for c in type(e).__mro__}
    if names & {
        "TimeoutError", "Timeout", "ConnectTimeout", "ReadTimeout",
        "TimeoutException", "ConnectionError", "ConnectError",
        "ConnectionResetError", "ConnectionAbortedError", "ConnectionRefusedError",
        "RemoteProtocolError", "TransportError", "APITimeoutError", "APIConnectionError",
    }:
        return True
    msg = str(e).lower()
    return "timed out" in msg or "timeout" in msg or "connection" in msg

def _make_vlm_call(client: VLMClient, prompt: str, image_pil: Image.Image, min_interval: float, log: Callable[[str], None], max_retries: int = 3) -> VlmResponse:
    global _last_call_time
    provider = client.provider
    last = _last_call_time.get(provider, 0.0)
    elapsed = time.time() - last
    if elapsed < min_interval:
        wait = min_interval - elapsed
        log(f"Rate limiter: waiting {wait:.2f} s before next VLM call")
        time.sleep(wait)

    buffered = io.BytesIO()
    image_pil.save(buffered, format="JPEG")
    img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

    # Retry the SAME frame until it succeeds. Transient failures (network drop,
    # timeout, rate limit) are retried indefinitely with exponential backoff
    # (5 s -> 60 s cap) so a disconnected/reconnected network resumes the frame
    # instead of producing a partial or corrupted result. Genuine (non-network)
    # API errors still fail fast.
    attempt = 0
    while True:
        attempt += 1
        try:
            log(f"Calling {client.provider} API (attempt {attempt})")
            response = client.chat(prompt, images=[img_b64])
            _last_call_time[provider] = time.time()
            return VlmResponse(text=response or "")
        except Exception as e:
            if _is_rate_limit(e) or _is_transient_network(e):
                wait = min(60.0, 5.0 * (2 ** (attempt - 1)))
                log(f"VLM API transient error ({type(e).__name__}: {e}); "
                    f"retrying in {wait:.1f}s (attempt {attempt})")
                time.sleep(wait)
            else:
                log(f"VLM API error: {e}")
                return VlmResponse()

# The relation vocabulary (class-ids + descriptions) and prompt templates are
# user-configured and persisted in the AppConfig store; they are passed in
# explicitly. There are no hardcoded defaults in the backend.

def _build_object_prompt_first_frame(grid_rows: int, grid_cols: int) -> str:
    return f"""Analyze the image with a {grid_rows}x{grid_cols} grid. Identify ALL people, vehicles, and objects.

Your output MUST be a JSON list. Each object MUST have the keys
"class", "description", and "blocks".

CRITICAL class rules (highest priority):
  1. Transportable objects (suitcases, packages, bags, backpacks, envelopes)
     MUST use class 'object'.
  2. ALL people use class 'person'. Do not miss any person.
  3. ALL vehicles (cars, trucks, vans, buses, motorcycles, bicycles)
     use class 'vehicle'.
  4. Other objects (chairs, tables, cups, phones) use their specific name.

"description": purely visual details (colors, clothing, shape). Do NOT
mention position or blocks.

"blocks": list of grid block numbers where the object appears. An object
spanning multiple blocks should list ALL of them.

Example:
[{{"class": "person", "description": "man in blue jacket", "blocks": [2, 6]}},
 {{"class": "object", "description": "black suitcase", "blocks": [6]}},
 {{"class": "vehicle", "description": "white sedan", "blocks": [3, 4, 7, 8]}},
 {{"class": "person", "description": "woman with backpack", "blocks": [7]}}]

Provide ONLY the JSON list."""

def _build_object_prompt_tracking_frame(
    grid_rows: int, grid_cols: int, previous_objects: list[dict]
) -> str:
    ctx_lines = [
        f"- ID: {obj['id']}, Class: {obj.get('class')}, Desc: {obj.get('description')}, Blocks: {obj.get('blocks')}"
        for obj in previous_objects
    ]
    ctx = "\n".join(ctx_lines) if ctx_lines else "(none)"
    return f"""Previous objects from the last frame:
{ctx}

Now analyze this NEW image with a {grid_rows}x{grid_cols} grid.
Identify ALL objects present and TRACK them by assigning IDs.

CRITICAL rules for "class" key:
  1. Transportable objects (suitcases, packages, bags) MUST use 'object'.
  2. People: 'person'. ALL vehicles (cars, trucks, vans, buses, motorcycles, bicycles): 'vehicle'.
  3. Other objects: their specific name.

Output MUST be a JSON list. Each object MUST have:
  - "class": the object category (see rules above)
  - "description": updated visual description (colors, clothing)
  - "blocks": list of grid blocks where the object is now
  - "id": the numeric ID from the previous frame if same object, or the string "new" if never seen before

ID reassignment rules:
  - Same class + overlapping blocks -> likely same object -> reuse ID
  - Same class + close blocks -> likely same object (moved) -> reuse ID
  - Objects that left the frame should NOT appear in the output
  - DO NOT reuse IDs for different-class objects
  - If unsure, assign "new" rather than reusing an ID incorrectly

Provide ONLY the JSON list."""

def _build_relation_prompt(relation_classids, objects_ctx: str,
                           descriptions: dict[str, str]) -> str:
    relations = "\n\n".join(
        f"{i}. {name}{classid}\n   {descriptions[name]}"
        for i, (name, classid) in enumerate(relation_classids, start=1)
    )
    return f"""Objects with their IDs and classes:
{objects_ctx}

Analyze the image and output ALL interactions you see using ONLY the numeric IDs provided. A single person can do multiple things at once.

You MUST consider EACH of the following relation types and output any that apply:

MANDATORY RELATIONS (output all that apply):

{relations}

--- FORMAT ---
Output a single line with space-separated relations.
Example: running(2) enter_or_exit_vehicle(2, 20)

If NONE of the above relations apply, output: none()

Do NOT output any other text."""

def _memory_prompt_context(
    memory: Optional[ObjectMemory],
    analysis_id: str,
    buffer: deque,
    frame_num: int,
    top_k: int,
    cap: int,
    log: Callable[[str], None],
) -> list[dict]:
    """Bounded tracking context = objects from the last N frames (recency)
    plus the top-k objects from all other frames whose embeddings are most
    similar to the recent window (retrieved via Chroma)."""
    if memory is None or not buffer:
        return []
    recent: list[dict] = []
    seen: set[str] = set()
    for _fr, objs in buffer:
        for o in objs:
            oid = str(o.get("id"))
            if oid in seen:
                continue
            seen.add(oid)
            recent.append(
                {"id": oid, "class": o.get("class"),
                 "description": o.get("description"), "blocks": o.get("blocks")}
            )
    query_embs = []
    for fr, objs in buffer:
        for o in objs:
            emb = memory.get_embedding(analysis_id, fr, o.get("id"))
            if emb is not None:
                query_embs.append(emb)
    similar: list[dict] = []
    if query_embs:
        for s in memory.query_similar(analysis_id, query_embs, top_k=top_k, exclude_frame=frame_num):
            sid = str(s["id"])
            if sid in seen:
                continue
            seen.add(sid)
            similar.append(
                {"id": sid, "class": s["class"],
                 "description": s["description"], "blocks": s["blocks"]}
            )
    ctx = recent + similar
    log(f"Memory context: {len(recent)} recent + {len(similar)} similar (cap {cap})")
    return ctx[:cap]

_RELATION_PATTERN = re.compile(r"(?i)([a-z_]+)\s*\(([^)\n]*)\)")

def _cls_label(cls: object) -> str:
    """Display label for an object class; fall back to 'object' when absent."""
    return str(cls) if cls else "object"


def _relation_allowed_classes(signature: str) -> set[str]:
    """Parse a relation signature like '(PersonID, VehicleID)' or
    '(VehicleID∨ObjectID)' into the set of allowed participant classes.
    '?' marks an optional argument; at least one participant is still required."""
    from service.relation_vocab import signature_classes
    return set(signature_classes(signature))

@dataclass
class FrameState:
    objects: dict = field(default_factory=dict)
    next_id: int = 1

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

def _strip_text_fences(text: str) -> str:
    """Remove markdown code fences/backticks and surrounding prose. Prose that
    wraps a JSON payload is tolerated by the parsers below regardless."""
    if not text:
        return ""
    text = text.strip()
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1:] if nl != -1 else ""
    return text.strip()

def _repair_json_text(text: str) -> str:
    """Lightweight repairs for common LLM JSON deviations: quote bare object keys
    and drop trailing commas before closing braces/brackets. Only consulted after
    a plain json.loads fails; the salvage path below still falls back to the
    original text, so an imperfect repair can never lose data."""
    text = re.sub(r'(?<!["\w])([A-Za-z_][A-Za-z0-9_]*)(\s*:)', r'"\1"\2', text)
    text = re.sub(r',\s*([}\]])', r'\1', text)
    return text

def _salvage_json_objects(text: str, log: Callable[[str], None]) -> list[dict]:
    """Recover structurally complete JSON objects from a corrupted payload by
    walking it with raw_decode, advancing past each object boundary. Malformed
    entries are skipped (and counted) so a single bad object no longer discards
    an entire frame."""
    decoder = json.JSONDecoder()
    objects: list[dict] = []
    discarded = 0
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "{" or c == "}":
            if c == "{":
                try:
                    obj, end = decoder.raw_decode(text, i)
                    if isinstance(obj, dict):
                        objects.append(obj)
                    i = end
                    continue
                except Exception:
                    discarded += 1
            close = text.find("}", i)
            if close == -1:
                break
            i = close + 1
            continue
        if c.isspace() or c == ",":
            i += 1
            continue
        nxt = text.find("{", i)
        close = text.find("}", i)
        if nxt == -1:
            break
        i = nxt if (close == -1 or nxt < close) else close
    if discarded:
        log(f"Discarded {discarded} malformed object entries")
    return objects

def _parse_relation_text(rel_text: str) -> list[tuple[str, str]]:
    """Extract (name, args) tuples from the VLM relation response. Matching is
    case-insensitive and whitespace-tolerant; a malformed relation simply fails
    to match and is dropped while intact ones are preserved. The 'none()'
    sentinel is returned as-is and filtered by the vocabulary check downstream."""
    found = _RELATION_PATTERN.findall(_strip_text_fences(rel_text))
    return [(name.lower(), args_str) for name, args_str in found]

def _find_object_list(value: object) -> list | None:
    """Dig through wrapper dicts to locate the object list (a list of dicts),
    e.g. {"objects": [...]} or {"result": {"objects": [...]}}."""
    if isinstance(value, list):
        return value if not value or all(isinstance(v, dict) for v in value) else None
    if isinstance(value, dict):
        for v in value.values():
            found = _find_object_list(v)
            if found is not None:
                return found
    return None

def _json_candidates(text: str) -> Iterator[str]:
    """Candidate JSON texts to try, from least to most invasive: the raw text,
    the repaired text, and cropped variants that drop leading prose up to the
    first '['/'{' (single/double-quoted wrappers like 'RESULTS: {...}')."""
    repaired = _repair_json_text(text)
    yield text
    yield repaired
    for src in (text, repaired):
        for opener in ("[", "{"):
            idx = src.find(opener)
            if idx > 0:
                yield src[idx:]

def _parse_object_json(raw: str, log: Callable[[str], None]) -> list[dict]:
    text = _strip_text_fences(raw or "")
    if not text:
        return []
    parsed = None
    for candidate in _json_candidates(text):
        try:
            parsed = json.loads(candidate)
            break
        except Exception:
            parsed = None
    if parsed is None and _json_repair_loads is not None:
        try:
            parsed = _json_repair_loads(text)
        except Exception as e:
            log(f"json_repair failed: {e}")
            parsed = None
    if isinstance(parsed, list):
        parsed_objs = parsed
    else:
        parsed_objs = _find_object_list(parsed)
        if parsed is not None and parsed_objs is None:
            log("Object JSON is not a list; ignoring")
            log(f"VLM returned: {text[:1000]}")
            return []
        if parsed is None:
            parsed_objs = _salvage_json_objects(text, log)
            if not parsed_objs:
                log("Failed to parse object JSON")
                log(f"VLM returned: {text[:1000]}")
                return []
    objs: list[dict] = []
    for obj in parsed_objs:
        if not isinstance(obj, dict):
            continue
        if not obj.get("class"):
            log(f"  -> Skipping object without class: {obj}")
            continue
        if isinstance(obj.get("blocks"), (int, float)):
            obj["blocks"] = [int(obj["blocks"])]
        elif not isinstance(obj.get("blocks"), list):
            obj["blocks"] = []
        objs.append(obj)
    return objs

def _persist_object(
    cursor: sqlite3.Cursor, frame_num: int, db_id: int, obj: dict,
    analysis_id: str, log: Callable[[str], None],
) -> None:
    for block in set(obj.get("blocks") or []):
        cursor.execute(
            "INSERT INTO VisualPerFrame (AnalysisID, Frame, ClassID, Class, Block, Description) VALUES (?, ?, ?, ?, ?, ?)",
            (analysis_id, frame_num, db_id, obj.get("class", "unknown"), block, obj.get("description", "")),
        )

def _persist_relation(
    cursor: sqlite3.Cursor,
    frame_num: int,
    event_id: int,
    name: str,
    class_id: str,
    analysis_id: str,
    log: Callable[[str], None],
) -> None:
    cid = int(class_id)
    existing = cursor.execute(
        "SELECT 1 FROM VisualRelation WHERE AnalysisID = ? AND Frame = ? AND RelationType = ? AND ClassID = ?",
        (analysis_id, frame_num, name, cid)
    ).fetchone()
    if existing:
        return
    cursor.execute(
        "INSERT OR IGNORE INTO VisualRelation "
        "(AnalysisID, Frame, RelationID, RelationType, ClassID) "
        "VALUES (?, ?, ?, ?, ?)",
        (analysis_id, frame_num, event_id, name, cid),
    )


def _analyze_frame(
    *,
    frame_num: int,
    frame_grid: Image.Image,
    frame_orig: Image.Image,
    cursor: sqlite3.Cursor,
    state: FrameState,
    client: VLMClient,
    grid_rows: int,
    grid_cols: int,
    min_interval: float,
    max_retries: int = 3,
    analysis_id: str = "",
    track_objects: bool = False,
    relation_classids: list[tuple[str, str]] | None = None,
    relation_descriptions: dict[str, str] | None = None,
    memory: Optional[ObjectMemory] = None,
    buffer: Optional[deque] = None,
    memory_top_k: int = 5,
    memory_cap: int = 30,
    log: Callable[[str], None],
) -> tuple[FrameState, list[dict]]:
    log(f"--- Frame {frame_num} ({client.provider}) ---")
    if not relation_classids or not relation_descriptions:
        raise ValueError("relation vocabulary not configured (relation_vocab)")

    previous: list[dict] = []
    if track_objects:
        previous = _memory_prompt_context(
            memory, analysis_id, buffer or deque(), frame_num,
            memory_top_k, memory_cap, log,
        )
    if not previous:
        obj_prompt = _build_object_prompt_first_frame(grid_rows, grid_cols)
    else:
        obj_prompt = _build_object_prompt_tracking_frame(grid_rows, grid_cols, previous)

    response = _make_vlm_call(client, obj_prompt, frame_grid, min_interval, log, max_retries)

    objects = _parse_object_json(response.text, log)
    # Fresh state: only this frame's objects. History lives in Chroma + the
    # recency buffer, so a VLM-empty frame no longer wipes ID continuity.
    new_state = FrameState(objects={}, next_id=state.next_id)

    if not track_objects:
        for obj in objects:
            db_id = new_state.next_id
            new_state.next_id += 1
            _persist_object(cursor, frame_num, db_id, obj, analysis_id, log)
            obj["db_id"] = db_id
            new_state.objects[str(db_id)] = obj
            log(f"  -> New {_cls_label(obj.get('class'))} #{db_id}")
    else:
        seen_in_frame: set[str] = set()
        prev_by_id: dict[str, dict] = {str(o["id"]): o for o in previous}
        unmatched_existing = set(prev_by_id.keys())
        max_id_used = new_state.next_id - 1
        for obj in objects:
            raw_id = str(obj.get("id", "new"))
            if raw_id != "new" and raw_id in seen_in_frame:
                log(f"  -> Skipping duplicate object #{raw_id} (same frame)")
                continue
            if raw_id != "new":
                seen_in_frame.add(raw_id)
                unmatched_existing.discard(raw_id)
            if raw_id == "new":
                obj_class = obj.get("class", "")
                obj_blocks = set(obj.get("blocks") or [])
                reidentified_id = None
                for eid in list(unmatched_existing):
                    eobj = prev_by_id[eid]
                    eobj_blocks = set(eobj.get("blocks") or [])
                    if eobj.get("class") != obj_class:
                        continue
                    if obj_blocks and eobj_blocks and not (obj_blocks & eobj_blocks):
                        continue
                    reidentified_id = eid
                    unmatched_existing.discard(eid)
                    break
                if reidentified_id is None:
                    for eid in list(unmatched_existing):
                        eobj = prev_by_id[eid]
                        eobj_blocks = set(eobj.get("blocks") or [])
                        if eobj.get("class") != obj_class:
                            continue
                        if obj_blocks and eobj_blocks and not (obj_blocks & eobj_blocks):
                            continue
                        reidentified_id = eid
                        unmatched_existing.discard(eid)
                        break
                if reidentified_id is None:
                    for eid in list(unmatched_existing):
                        eobj = prev_by_id[eid]
                        if eobj.get("class") != obj_class:
                            continue
                        reidentified_id = eid
                        unmatched_existing.discard(eid)
                        break
                if reidentified_id is not None:
                    db_id = int(reidentified_id)
                    log(f"  -> Re-identified {_cls_label(obj_class)} #{db_id}")
                else:
                    db_id = new_state.next_id
                    new_state.next_id += 1
                    _persist_object(cursor, frame_num, db_id, obj, analysis_id, log)
                    log(f"  -> New {_cls_label(obj_class)} #{db_id}")
            else:
                try:
                    db_id = int(raw_id)
                except (TypeError, ValueError):
                    log(f"  -> Skipping object with malformed id '{raw_id}'")
                    continue
                log(f"  -> Tracked {_cls_label(obj.get('class'))} #{db_id}")
            for block in set(obj.get("blocks") or []):
                cursor.execute(
                    "INSERT OR IGNORE INTO VisualPerFrame (AnalysisID, Frame, ClassID, Class, Block, Description) VALUES (?, ?, ?, ?, ?, ?)",
                    (analysis_id, frame_num, db_id, obj.get("class", "unknown"), block, obj.get("description", "")),
                )
            obj["db_id"] = db_id
            new_state.objects[str(db_id)] = obj
            max_id_used = max(max_id_used, db_id)
        if max_id_used >= new_state.next_id:
            new_state.next_id = max_id_used + 1

    if track_objects and memory is not None and new_state.objects:
        memory.save_frame(analysis_id, frame_num, list(new_state.objects.values()),
                          grid_rows, grid_cols, frame_orig, log=log)

    log("Analyzing relations...")
    objects_ctx_lines = [
        f"- ID: {oid}, Desc: {o.get('description')}, Blocks: {o.get('blocks')}"
        for oid, o in new_state.objects.items()
    ]
    objects_ctx = "\n".join(objects_ctx_lines) if objects_ctx_lines else "(no objects)"
    rel_prompt = _build_relation_prompt(
        relation_classids, objects_ctx,
        descriptions=relation_descriptions)

    rel_response = _make_vlm_call(client, rel_prompt, frame_orig, min_interval, log, max_retries)

    if rel_response.text:
        rel_text = rel_response.text.strip()
        log(f"Relations: {rel_text}")
        known_class_ids = set(new_state.objects.keys())
        allowed_by_rel = {name: _relation_allowed_classes(sig) for name, sig in relation_classids}
        vocab_names = set(allowed_by_rel)
        for event_id, (name, args_str) in enumerate(
            _parse_relation_text(rel_text), start=1
        ):
            if name not in vocab_names:
                log(f"  -> Skipping non-vocab relation '{name}'")
                continue
            allowed = allowed_by_rel[name]
            arg_ids = [a.strip() for a in args_str.split(",")]
            matched_ids = []
            for class_id in arg_ids:
                if class_id in known_class_ids and new_state.objects[class_id].get("class") in allowed:
                    matched_ids.append(class_id)
                else:
                    log(f"  -> Skipping hallucinated id '{class_id}' in relation '{name}'")
            if not matched_ids:
                continue
            for class_id in set(matched_ids):
                _persist_relation(cursor, frame_num, event_id, name, class_id, analysis_id, log)
                rel_cls = _cls_label(new_state.objects[class_id].get("class"))
                log(
                    f"  -> Saved relation {name}({rel_cls}) #{class_id}, Frame={frame_num}"
                )

    return new_state, [
        {"id": str(o["db_id"]), "class": o.get("class"),
         "description": o.get("description"), "blocks": o.get("blocks")}
        for o in new_state.objects.values()
    ]

class VisualServiceImpl(VisualService):
    def __init__(self, max_retries: int = 3, relation_classids=None,
                 relation_descriptions=None, memory_db_dir="data/vector_db",
                 memory_n: int = 3, memory_top_k: int = 5, memory_cap: int = 30,
                 embed_provider: str = "huggingface",
                 embed_model: str = "google/siglip-base-patch16-224",
                 ollama_base_url: str = "http://localhost:11434",
                 device: str = "cpu"):
        if not relation_classids or not relation_descriptions:
            raise ValueError("relation vocabulary not configured (relation_vocab)")
        self.max_retries = max_retries
        self.relation_classids = [tuple(x) for x in relation_classids]
        self.relation_descriptions = dict(relation_descriptions)
        self.device = device
        self.memory = ObjectMemory(
            memory_db_dir,
            embed_provider=embed_provider,
            embed_model=embed_model,
            ollama_base_url=ollama_base_url,
            device=device,
        ) if memory_db_dir else None
        self.memory_n = int(memory_n)
        self.memory_top_k = int(memory_top_k)
        self.memory_cap = int(memory_cap)

    def run_pipeline(
        self,
        *,
        video_path: str,
        conn: sqlite3.Connection,
        client: VLMClient,
        grid_rows: int,
        grid_cols: int,
        frame_step: int,
        min_interval: float = 0.0,
        analysis_id: str = "",
        track_objects: bool = False,
        log: Callable[[str], None] = print,
        merge_gap_frames: int | None = None,
    ) -> None:
        log(f"Starting video analysis: {video_path}")
        log(f"Provider: {client.provider}, Model: {client.model}, Grid: {grid_rows}x{grid_cols}")
        log(f"Visual sampling: 1 frame every {frame_step} source frames")
        if track_objects:
            embed = self.memory._embed_provider if self.memory else "huggingface"
            model = self.memory._embed_model if self.memory else "google/siglip-base-patch16-224"
            log(f"Object memory: recency={self.memory_n} frame(s), top_k={self.memory_top_k}, cap={self.memory_cap}, "
                f"embed={embed}:{model}")

        cursor = conn.cursor()
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            log(f"ERROR: cannot open video at {video_path}")
            return

        if track_objects and self.memory is not None:
            self.memory.clear(analysis_id)

        state = FrameState()
        buffer: deque = deque(maxlen=self.memory_n) if track_objects else deque()
        frame_count = 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_count % frame_step == 0:
                    log(f"--- FRAME {frame_count} ---")
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    pil = Image.fromarray(rgb)
                    pil_grid = draw_grid_on_image(pil, grid_rows, grid_cols)
                    state, frame_objects = _analyze_frame(
                        frame_num=frame_count,
                        frame_grid=pil_grid,
                        frame_orig=pil,
                        cursor=cursor,
                        state=state,
                        client=client,
                        grid_rows=grid_rows,
                        grid_cols=grid_cols,
                        min_interval=min_interval,
                        max_retries=self.max_retries,
                        analysis_id=analysis_id,
                        track_objects=track_objects,
                        relation_classids=self.relation_classids,
                        relation_descriptions=self.relation_descriptions,
                        memory=self.memory if track_objects else None,
                        buffer=buffer,
                        memory_top_k=self.memory_top_k,
                        memory_cap=self.memory_cap,
                        log=log,
                    )
                    buffer.append((frame_count, frame_objects))
                frame_count += 1
        except Exception as e:
            log(f"CRITICAL ERROR in VLM pipeline: {e}")
        finally:
            cap.release()
        log(f"VLM analysis complete. {frame_count} video frames processed.")
        # Build intervals atomically (frame-level + interval-level in one commit)
        interval_svc = IntervalServiceImpl()
        for msg in interval_svc.build_visual_and_save(
            conn,
            frame_step,
            analysis_id=analysis_id,
            log_fn=log,
            merge_gap_frames=merge_gap_frames,
        ):
            log(msg)
        conn.commit()
