"""The catalogs are closed: changing one means changing this test on purpose."""

from xai.contract.reasons import CheckName, InputError, NoteCode, Reason


def test_reason_catalog() -> None:
    assert {r.value for r in Reason} == {
        "keyframes_not_persisted",
        "vlm_output_not_persisted",
        "reid_similarity_not_persisted",
        "visual_confidence_not_recorded",
        "fps_not_recorded",
        "analysis_record_missing",
        "backend_version_not_recorded",
        "origin_not_identifiable",
        "modality_rule_absent",
        "glossary_definition_not_in_system",
        "conflicting_records",
    }


def test_input_error_catalog() -> None:
    assert {e.value for e in InputError} == {
        "ANALYSIS_NOT_FOUND",
        "ANALYSIS_NOT_READY",
        "ANALYSIS_PARAMS_MISSING",
        "CONFIG_MISSING",
        "RULE_NOT_FOUND",
        "EVENT_NOT_REPRODUCIBLE",
        "UNSUPPORTED_CONSTRUCT",
        "ROW_SCHEMA_AMBIGUOUS",
    }


def test_check_names() -> None:
    assert {c.value for c in CheckName} == {"completeness", "referential_closure"}


def test_note_codes() -> None:
    assert {n.value for n in NoteCode} == {
        "selection_basis",
        "params_unit",
        "saved_text_diverges_from_structure",
        "c_labels_by_kind",
    }


def test_codes_are_their_own_names() -> None:
    for catalog in (Reason, NoteCode, CheckName):
        for member in catalog:
            assert member.value == member.name.lower()
    for error in InputError:
        assert error.value == error.name
