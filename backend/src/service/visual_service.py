from abc import ABC, abstractmethod
from typing import Callable, Optional
import sqlite3
from utils.vlm_client import VLMClient

class VisualService(ABC):
    @abstractmethod
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
        pass
