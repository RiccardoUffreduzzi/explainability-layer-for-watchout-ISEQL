"""Closed catalogs used by the contract draft.

A new code is added here, together with a test, never at runtime.
"""

from enum import Enum


class Reason(str, Enum):
    """Why a field of the draft is null (``Unavailable.reason``)."""

    KEYFRAMES_NOT_PERSISTED = "keyframes_not_persisted"
    """The WatchOut version in use does not store key frames."""

    VLM_OUTPUT_NOT_PERSISTED = "vlm_output_not_persisted"
    """The key-frame version does not store the VLM output for that frame."""

    REID_SIMILARITY_NOT_PERSISTED = "reid_similarity_not_persisted"
    """Re-ID similarity and gallery match are not stored."""

    VISUAL_CONFIDENCE_NOT_RECORDED = "visual_confidence_not_recorded"
    """``VisualPerInterval`` has no confidence column."""

    FPS_NOT_RECORDED = "fps_not_recorded"
    """``Analyses.SamplingRate`` is missing or zero."""

    ANALYSIS_RECORD_MISSING = "analysis_record_missing"
    """A column of ``Analyses`` is empty."""

    BACKEND_VERSION_NOT_RECORDED = "backend_version_not_recorded"
    """Neither ``__version__`` nor git is available."""

    ORIGIN_NOT_IDENTIFIABLE = "origin_not_identifiable"
    """A condition C row matches no row of Evento_A or Evento_B."""

    MODALITY_RULE_ABSENT = "modality_rule_absent"
    """The event has no rule for that modality."""

    GLOSSARY_DEFINITION_NOT_IN_SYSTEM = "glossary_definition_not_in_system"
    """The term has no definition in the system nor in ``glossary.yaml``."""

    CONFLICTING_RECORDS = "conflicting_records"
    """Two WatchOut sources give different values for the same field."""


class InputError(str, Enum):
    """Why K1 refuses a request before reading the draft (``HarvestFailure``, stage ``input``)."""

    ANALYSIS_NOT_FOUND = "ANALYSIS_NOT_FOUND"
    """No ``Analyses`` row with that ID."""

    ANALYSIS_NOT_READY = "ANALYSIS_NOT_READY"
    """``Stage`` is not ``done``."""

    ANALYSIS_PARAMS_MISSING = "ANALYSIS_PARAMS_MISSING"
    """``--params saved`` without ``DeltasJson``, or ``DeltasJson`` lacks keys the rule needs."""

    CONFIG_MISSING = "CONFIG_MISSING"
    """``AppConfig`` has no ``audio_taxonomy`` or ``relation_vocab``."""

    RULE_NOT_FOUND = "RULE_NOT_FOUND"
    """No ``EventSpec(id, condition)``."""

    EVENT_NOT_REPRODUCIBLE = "EVENT_NOT_REPRODUCIBLE"
    """The requested row is not among the rows the engine produces today."""

    UNSUPPORTED_CONSTRUCT = "UNSUPPORTED_CONSTRUCT"
    """The model contains ``group_id`` or ``query_ref`` (form F4)."""

    ROW_SCHEMA_AMBIGUOUS = "ROW_SCHEMA_AMBIGUOUS"
    """Form F3 with columns that cannot be traced to a branch."""


class CheckName(str, Enum):
    """The two closing checks of K1."""

    COMPLETENESS = "completeness"
    REFERENTIAL_CLOSURE = "referential_closure"


class NoteCode(str, Enum):
    """Facts about how K1 read the data, reported in ``harvest_report.notes``.

    K2 may turn a note into a knowledge limit, so the set is closed like the reasons.
    """

    SELECTION_BASIS = "selection_basis"
    """Which intervals were reported and why (pertinence filter)."""

    PARAMS_UNIT = "params_unit"
    """How the authored parameter values relate to the values the engine used."""

    SAVED_TEXT_DIVERGES_FROM_STRUCTURE = "saved_text_diverges_from_structure"
    """The saved ``iseql_text`` differs from the executed structure."""

    C_LABELS_BY_KIND = "c_labels_by_kind"
    """Condition C columns were mapped to their kind, not to their label."""
