"""Order of the arguments of a visual interval: the signature decides it or nobody does."""

from xai.k1_harvester.evidence import order_args
from xai.k1_harvester.ports import ParticipantRow


def _p(class_id: int, name: str) -> ParticipantRow:
    return ParticipantRow(relation_id=59, class_id=class_id, class_name=name)


def test_a_class_per_slot_fixes_the_order() -> None:
    result = order_args([_p(4, "object"), _p(3, "person")], [["person"], ["object"]])

    assert result.ordered
    assert [p.class_id for p in result.participants] == [3, 4]


def test_a_slot_with_several_classes_still_fixes_the_order() -> None:
    result = order_args([_p(4, "vehicle"), _p(2, "person")], [["person"], ["vehicle", "object"]])

    assert result.ordered
    assert [p.class_id for p in result.participants] == [2, 4]


def test_two_slots_of_the_same_class_do_not() -> None:
    result = order_args([_p(2, "person"), _p(1, "person")], [["person"], ["person"]])

    assert not result.ordered
    assert [p.class_id for p in result.participants] == [1, 2]


def test_participants_that_do_not_fit_the_slots_do_not() -> None:
    missing = order_args([_p(2, "person")], [["person"], ["object"]])
    extra = order_args([_p(2, "person"), _p(5, "object"), _p(6, "object")], [["person"], ["object"]])
    wrong = order_args([_p(2, "vehicle"), _p(5, "object")], [["person"], ["object"]])

    assert not missing.ordered and not extra.ordered and not wrong.ordered
    assert [p.class_id for p in extra.participants] == [2, 5, 6]


def test_without_a_signature_the_order_is_by_class_id() -> None:
    result = order_args([_p(9, "person"), _p(3, "object")], None)

    assert not result.ordered
    assert [p.class_id for p in result.participants] == [3, 9]
