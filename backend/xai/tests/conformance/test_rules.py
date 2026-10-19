"""The rule K1 reads is the rule WatchOut compiles.

1. Every temporal operator K1 reports, with its parameters as passed to the SQL,
   renders through WatchOut's own helper to a fragment of the compiled SQL.
2. Each branch of a condition C rule is the A or B rule of its modality: same
   selections, conditions, projection and operators.
"""

import inspect
from collections.abc import Callable
from typing import Any, cast

from iseql.helpers import OPERATOR_HELPERS
from service.impl.events_service_impl import queries_for_condition

from xai.adapters.watchout.engine import converted_deltas
from xai.contract.model import Condition
from xai.k1_harvester.context import MODALITY_CONDITIONS
from xai.k1_harvester.ports import Branch, ParamsSnapshot, ResolvedOperator, RuleSnapshot
from xai.k1_harvester.predicates import branch_modality
from xai.k1_harvester.rule.form_detector import ModelFormDetector
from xai.tests.harness import PinnedReader

FPS = 24
CONDITIONS: tuple[Condition, ...] = ("A", "B", "C")


def _layout(reader: PinnedReader, rule: RuleSnapshot) -> tuple[Any, Any]:
    form = ModelFormDetector().detect(rule)
    return form, reader.rule_layout(rule, form)


def _operators(
    reader: PinnedReader, rule: RuleSnapshot, branch: Branch, params: ParamsSnapshot
) -> list[ResolvedOperator]:
    form, _ = _layout(reader, rule)
    return [
        reader.resolve_operator(rule, form, branch, k, params, FPS) for k in range(len(branch.intervals) - 1)
    ]


def _fragment(operator: ResolvedOperator, left: str, right: str) -> str:
    helper = cast(Callable[..., str], OPERATOR_HELPERS[operator.name][0])
    accepted = inspect.signature(helper).parameters
    kwargs = {
        p.name: (None if p.engine_value in ("inf", "∞") else p.engine_value)
        for p in operator.params
        if p.name in accepted
    }
    cols = ("st", "et") if operator.compare_domain == "seconds" else ("sf", "ef")
    return " ".join(helper(left, right, cols=cols, **kwargs).split())


def test_every_seed_rule_has_a_layout(reader: PinnedReader) -> None:
    refs = []
    for condition in CONDITIONS:
        for rule in reader.rules(condition):
            _, layout = _layout(reader, rule)
            assert layout.branches, rule.ref
            assert layout.columns is not None, f"{rule.ref}: {layout.columns_problem}"
            refs.append(rule.ref)

    assert len(refs) == 16


def test_operators_are_those_of_the_compiled_sql(reader: PinnedReader) -> None:
    params = reader.default_params()
    checked, failures = 0, []
    for condition in CONDITIONS:
        sql_by_event = queries_for_condition(
            condition, converted_deltas(params, FPS), "any_analysis", conn=reader.conn, fps=FPS
        )
        for rule in reader.rules(condition):
            sql = " ".join(sql_by_event[rule.event_type].split())
            _, layout = _layout(reader, rule)
            for branch in layout.branches:
                for k, operator in enumerate(_operators(reader, rule, branch, params)):
                    fragment = _fragment(operator, branch.intervals[k].alias, branch.intervals[k + 1].alias)
                    checked += 1
                    if fragment not in sql:
                        failures.append(f"{rule.ref} {branch.name} pair {k + 1}: {fragment} not in the SQL")

    assert failures == []
    assert checked >= 10


def _branch_facts(reader: PinnedReader, rule: RuleSnapshot, branch: Branch, params: ParamsSnapshot) -> Any:
    return (
        [i.selection for i in branch.intervals],
        [(c.left, c.op, c.right, c.duration_value, c.duration_unit) for c in branch.conditions],
        branch.projection,
        [
            (o.name, o.compare_domain, [(p.name, p.engine_value) for p in o.params])
            for o in _operators(reader, rule, branch, params)
        ],
    )


def test_each_c_branch_is_the_rule_of_its_modality(reader: PinnedReader) -> None:
    params = reader.default_params()
    vocabulary = reader.vocabulary()
    assert vocabulary is not None
    compared = []
    for rule in reader.rules("C"):
        _, layout = _layout(reader, rule)
        for branch in layout.branches:
            modality = branch_modality(branch, vocabulary)
            assert modality in MODALITY_CONDITIONS, f"{rule.ref} {branch.name} mixes modalities"
            single = reader.rule(rule.event_type, MODALITY_CONDITIONS[modality])
            if single is None:
                continue
            _, single_layout = _layout(reader, single)
            assert len(single_layout.branches) == 1
            assert _branch_facts(reader, rule, branch, params) == _branch_facts(
                reader, single, single_layout.branches[0], params
            ), f"{rule.ref} {branch.name} differs from {single.ref}"
            compared.append(f"{rule.ref} {branch.name}")

    assert len(compared) >= 6
