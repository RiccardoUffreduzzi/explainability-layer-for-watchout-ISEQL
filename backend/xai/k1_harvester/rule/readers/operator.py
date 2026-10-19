"""``temporal_operator`` nodes: the operator between consecutive intervals of a branch.

The name is not stored in the model: WatchOut deduces it from the template geometry
or reads an ``operator_overrides`` entry. The reader asks the engine
(``WatchOutReader.resolve_operator``) and reports each parameter as written and as
passed to the SQL.
"""

from xai.contract.ids import operator_id, projection_id
from xai.contract.model import ConstraintNode, OperatorParam, TemporalOperatorNode, TemporalOperatorPayload
from xai.contract.primitives import SourceRef, Stage
from xai.k1_harvester.ports import Branch, ResolvedOperator, ResolvedParam
from xai.k1_harvester.rule.scope import RuleScope

GREEK = {"delta": "δ", "epsilon": "ε", "zeta": "ζ", "eta": "η", "rho": "ρ"}

ENGINE_DEFAULTS = SourceRef(
    stage=Stage.CODE,
    store="backend/src/iseql/compiler.py",
    record_id="_operators_between_slots: zeta and eta '<=', rho 0 when the delta_map entry has none",
    mode="read",
)


class OperatorReader:
    def read(self, scope: RuleScope) -> list[ConstraintNode]:
        branch = scope.branch
        if branch is None:
            return []
        ctx = scope.ctx
        nodes: list[ConstraintNode] = []
        for pair in range(len(branch.intervals) - 1):
            resolved = ctx.reader.resolve_operator(
                ctx.rule, ctx.form, branch, pair, ctx.params, ctx.analysis.fps
            )
            first, second = branch.intervals[pair], branch.intervals[pair + 1]
            nodes.append(
                TemporalOperatorNode(
                    constraint_id=operator_id(branch.name, pair + 1),
                    kind="temporal_operator",
                    branch=branch.name,
                    modality=scope.modality([first, second]),
                    variables=[first.alias, second.alias],
                    parent=projection_id(branch.name),
                    payload=TemporalOperatorPayload(
                        name=resolved.name,  # type: ignore[arg-type]
                        resolution=resolved.resolution,
                        resolution_detail=resolved.resolution_detail,
                        params=[self._param(scope, branch, pair, resolved, p) for p in resolved.params],
                    ),
                    text=resolved.text,
                    source_ref=scope.rule.source(self._pointer(branch, pair, resolved)),
                )
            )
        return nodes

    @staticmethod
    def _pointer(branch: Branch, pair: int, resolved: ResolvedOperator) -> str:
        """The part of the model that decides the operator: override, delta_map entry or template."""
        if resolved.override_index is not None:
            return f"/operator_overrides/{resolved.override_index}"
        if resolved.delta_map_key is not None:
            return f"/delta_map/{resolved.delta_map_key}"
        return f"/intervals/{branch.intervals[pair].index}"

    @staticmethod
    def _param(
        scope: RuleScope, branch: Branch, pair: int, resolved: ResolvedOperator, param: ResolvedParam
    ) -> OperatorParam:
        if param.origin == "named_key":
            assert param.key is not None
            source = scope.ctx.params.source_for(param.key, scope.rule.ref)
        elif param.origin == "literal":
            source = scope.rule.source(param.pointer)
        elif param.origin == "template_geometry":
            source = scope.rule.source(f"/intervals/{branch.intervals[pair].index}")
        else:
            source = ENGINE_DEFAULTS
        strictness = param.name in ("zeta", "eta")
        return OperatorParam(
            name=GREEK[param.name],  # type: ignore[arg-type]
            raw=param.key,
            value=param.value,  # type: ignore[arg-type]
            unit=None if strictness else param.unit,
            engine_value=param.engine_value,  # type: ignore[arg-type]
            compare_domain=resolved.compare_domain,
            origin=param.origin,
            source_ref=source,
        )
