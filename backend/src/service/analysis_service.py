from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from models.analysis import RunState


class AnalysisService(ABC):

    @abstractmethod
    def get_run(self, analysis_id: str) -> RunState:
        pass

    @abstractmethod
    def start_analysis(
        self,
        *,
        video_path: Path,
        video_filename: str,
        condition: str,
        vlm_provider: str,
        model: str,
        grid_rows: int,
        grid_cols: int,
        frame_rate: float,
        sampling_rate: float,
        vlm_delay: float,
        max_retries: int,
        audio_provider: str,
        audio_model: str,
        audio_quantization: str,
        audio_window: float,
        audio_hop: float,
    ) -> RunState:
        pass

    @abstractmethod
    def get_status(self, analysis_id: str) -> dict:
        pass

    @abstractmethod
    def list_analyses(self) -> list[dict]:
        pass

    @abstractmethod
    def detect_event(
        self,
        *,
        analysis_id: str,
        event_type: str,
        condition: str,
    ) -> dict:
        pass

    @abstractmethod
    def load_from_db(self) -> int:
        pass

    @abstractmethod
    def stop_analysis(self, analysis_id: str) -> None:
        pass

    @abstractmethod
    def delete_analysis(self, analysis_id: str) -> None:
        pass

    @abstractmethod
    def reset_database(self) -> None:
        pass
