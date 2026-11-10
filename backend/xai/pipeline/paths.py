"""Where each stage of the report pipeline keeps its files.

K1 writes the drafts, K2 the sources of truth and K4 the plans, side by side::

    <analysis_id>/<event type>/<ev_id>.json        K1's draft
    <analysis_id>/k2/<event type>/<ev_id>.json     K2's source of truth
    <analysis_id>/k4/<event type>/<ev_id>.json     K4's plan

The functions live here, and not in a stage, so that no stage has to import another one.
"""

from pathlib import Path

K2_FOLDER = "k2"
K4_FOLDER = "k4"


def stage_path(draft_path: Path, folder: str) -> Path:
    """The file of the stage kept in ``folder``, for the K1 draft at ``draft_path``."""
    event_dir = draft_path.parent
    return event_dir.parent / folder / event_dir.name / draft_path.name


def k2_path(draft_path: Path) -> Path:
    """Where K2 wrote the source of truth of the draft at ``draft_path``."""
    return stage_path(draft_path, K2_FOLDER)


def k4_path(draft_path: Path) -> Path:
    """Where K4 writes the plan of the draft at ``draft_path``."""
    return stage_path(draft_path, K4_FOLDER)


def k4_path_of_source(source: Path) -> Path:
    """The plan file that goes with the K2 file ``<analysis_id>/k2/<event type>/<ev_id>.json``."""
    event_dir = source.parent
    return event_dir.parent.parent / K4_FOLDER / event_dir.name / source.name
