from __future__ import annotations

import sqlite3
from typing import Callable, Iterator

import pandas as pd

from utils.api_logger import get_logger
from service.interval_service import IntervalService

log = get_logger(__name__)

# Sightings of the same relation closer than this many samples join one interval.
_MERGE_TOLERANCE_SAMPLES = 2


class IntervalServiceImpl(IntervalService):
    @staticmethod
    def merge_tolerance_samples() -> int:
        """Largest gap, in sampled frames, that still merges two sightings into one interval"""
        return _MERGE_TOLERANCE_SAMPLES

    def build_visual_and_save(
        self,
        conn: sqlite3.Connection,
        sampling_rate: int,
        analysis_id: str = "",
        log_fn: Callable[[str], None] = print,
    ) -> Iterator[str]:
        log_fn(f"Starting post-processing (sampling rate: {sampling_rate})...")

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
            merge_threshold = self.merge_tolerance_samples() * sampling_rate
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
