"""Where each stage of the report pipeline keeps its files.

K1 writes the drafts, K2 the sources of truth, K4 the plans and K5 the reports:

    <analysis_id>/<event type>/<ev_id>.json              K1's draft
    <analysis_id>/k2/<event type>/<ev_id>.json           K2's source of truth
    <analysis_id>/k4/<event type>/<ev_id>.json           K4's plan
    <analysis_id>/k5/<event type>/<ev_id>.json           Report 1 (and .md, .trace.json beside it)

The functions live here so that no stage has to import another one.
"""

from pathlib import Path

K2_FOLDER = "k2"
K4_FOLDER = "k4"
K5_FOLDER = "k5"


def stage_path(draft_path: Path, folder: str) -> Path:
    """The file of the stage kept in ``folder``, for the K1 draft at ``draft_path``."""
    event_dir = draft_path.parent
    return event_dir.parent / folder / event_dir.name / draft_path.name


def k2_path(draft_path: Path) -> Path:
    """Where K2 wrote the source of truth"""
    return stage_path(draft_path, K2_FOLDER)


def k4_path(draft_path: Path) -> Path:
    """Where K4 writes the plan of the draft"""
    return stage_path(draft_path, K4_FOLDER)


def k4_path_of_source(source: Path) -> Path:
    """The plan file that goes with the K2 file ``<analysis_id>/k2/<event type>/<ev_id>.json``."""
    event_dir = source.parent
    return event_dir.parent.parent / K4_FOLDER / event_dir.name / source.name


def k5_path(draft_path: Path) -> Path:
    """Where K5 writes Report 1 of the draft at ``draft_path`` (the JSON file of the report)."""
    return stage_path(draft_path, K5_FOLDER)


def sibling_path(stage_file: Path, folder: str) -> Path:
    """The file of the stage kept in ``folder`` beside the file of another stage.

    ``<analysis_id>/k4/<event type>/<ev_id>.json`` -> ``<analysis_id>/<folder>/<event type>/<ev_id>.json``.
    """
    event_dir = stage_file.parent
    return event_dir.parent.parent / folder / event_dir.name / stage_file.name
