from __future__ import annotations

import sqlite3
from typing import Callable, Iterator

import pandas as pd

from utils.api_logger import get_logger
from service.interval_service import IntervalService

log = get_logger(__name__)


class IntervalServiceImpl(IntervalService):
    def build_visual_and_save(
        self,
        conn: sqlite3.Connection,
        frame_step: int,
        analysis_id: str = "",
        log_fn: Callable[[str], None] = print,
        merge_gap_frames: int | None = None,
    ) -> Iterator[str]:
        log_fn(f"Starting post-processing (frame step: {frame_step})...")

        try:
            try:
                df = pd.read_sql_query(
                    "SELECT * FROM VisualRelation WHERE AnalysisID = ?",
                    conn, params=(analysis_id,)
                )
            except Exception as e:
                log_fn(f"Error reading VisualRelation: {e}")
                return

            if df.empty:
                log_fn("No vis relations found; aborting interval construction.")
                return

            log_fn(f"Loaded {len(df)} vis-relation rows.")

            # Build class mapping: ClassID -> Class
            try:
                class_df = pd.read_sql_query(
                    "SELECT DISTINCT ClassID, Class FROM VisualPerFrame WHERE AnalysisID = ?",
                    conn, params=(analysis_id,)
                )
                class_map = dict(zip(class_df["ClassID"], class_df["Class"]))
            except Exception:
                class_map = {}

            events_per_frame = (
                df.groupby(["Frame", "RelationID", "RelationType"])["ClassID"]
                .apply(lambda x: tuple(sorted(x.tolist())))
                .reset_index()
                .rename(columns={"ClassID": "Participants"})
            )

            log_fn("Computing duration intervals with merge logic...")
            unique_events = events_per_frame.groupby(["RelationType", "Participants"])
            # Preserve legacy behaviour unless an experiment supplies an explicit
            # source-frame tolerance.  The latter lets controlled sampling
            # experiments avoid changing the wall-clock merge tolerance.
            merge_threshold = (
                int(merge_gap_frames)
                if merge_gap_frames is not None
                else 2 * frame_step
            )
            if merge_threshold < 0:
                raise ValueError("merge_gap_frames must be non-negative")
            processed: list[dict] = []

            for (rel_type, participants), group in unique_events:
                frames = sorted(group["Frame"].unique().tolist())
                if not frames:
                    continue
                start_frame = frames[0]
                last_seen = frames[0]
                for current in frames[1:]:
                    if current - last_seen > merge_threshold:
                        processed.append({
                            "RelationType": rel_type, "StartFrame": start_frame,
                            "EndFrame": last_seen, "Participants": participants,
                        })
                        start_frame = current
                    last_seen = current
                processed.append({
                    "RelationType": rel_type, "StartFrame": start_frame,
                    "EndFrame": last_seen, "Participants": participants,
                })

            if not processed:
                log_fn("No consolidated intervals found after filtering.")
                return

            log_fn(f"Consolidated {len(processed)} unique relation intervals.")

            cursor = conn.cursor()
            valid = [iv for iv in processed if iv["StartFrame"] <= iv["EndFrame"]]
            if not valid:
                log_fn("No intervals with sufficient duration found; nothing saved.")
                conn.commit()
                return

            log_fn(f"Filtered to {len(valid)} intervals with valid duration; saving...")
            for iv in valid:
                cursor.execute(
                    "INSERT INTO VisualPerInterval (AnalysisID, RelationType, StartFrame, EndFrame) VALUES (?, ?, ?, ?)",
                    (analysis_id, str(iv["RelationType"]), int(iv["StartFrame"]), int(iv["EndFrame"])),
                )
                rel_id = cursor.lastrowid
                for oid in iv["Participants"]:
                    cid = int(oid)
                    cls = class_map.get(cid, "unknown")
                    cursor.execute(
                        "INSERT OR IGNORE INTO VisualParticipant (RelationID, ClassID, Class) VALUES (?, ?, ?)",
                        (rel_id, cid, cls),
                    )
            conn.commit()
            log_fn("Intervals saved successfully.")
        except Exception as e:
            log_fn(f"CRITICAL ERROR in post-processing: {e}")
            return

        yield "Interval construction complete."
