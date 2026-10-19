"""The ``rule`` section: text, structure and nodes of the executed rule.

The nodes are those of the saved model as the compiler executes them; ``parent``
is containment only and K4 decides the order of the explanation.
"""

import difflib
from collections.abc import Sequence

from xai.contract.model import ConstraintNode, Note, RuleRecord, TemporalOperatorNode
from xai.contract.reasons import NoteCode
from xai.k1_harvester.context import HarvestContext
from xai.k1_harvester.gaps import LINEAGE
from xai.k1_harvester.ports import ParamsSnapshot
from xai.k1_harvester.rule.readers import DEFAULT_READERS, NodeReader
from xai.k1_harvester.rule.readers.set_operation import projection_parents
from xai.k1_harvester.rule.scope import RuleScope


class RuleHarvester:
    def __init__(self, readers: Sequence[NodeReader] = DEFAULT_READERS) -> None:
        self.readers = tuple(readers)

    def harvest(self, ctx: HarvestContext) -> tuple[RuleRecord, list[Note]]:
        nodes = self.nodes(ctx)
        expression = ctx.reader.render_rule(ctx.rule, ctx.params)
        saved = ctx.rule.model.get("iseql_text")
        notes = []
        if isinstance(saved, str) and saved.strip():
            structural = ctx.reader.render_rule(ctx.rule, self._own_defaults(ctx))
            if structural != saved:
                notes.append(
                    Note(
                        code=NoteCode.SAVED_TEXT_DIVERGES_FROM_STRUCTURE,
                        detail=_divergence(saved, structural),
                    )
                )
        else:
            saved = expression
            notes.append(
                Note(
                    code=NoteCode.SAVED_TEXT_DIVERGES_FROM_STRUCTURE,
                    detail="the EventSpec model has no iseql_text: expression_saved is the rendered text",
                )
            )
        params_note = _params_note(nodes)
        if params_note is not None:
            notes.append(params_note)
        branch = ctx.origin.branch
        projection = list(branch.projection) if branch else [c.label for c in ctx.layout.columns or ()]
        record = RuleRecord(
            expression=expression,
            expression_saved=saved,
            structure_ref=ctx.rule.source(),
            model_form=ctx.form,
            projection=projection,
            bindings=None,
            constraints=nodes,
            unavailable={"bindings": LINEAGE},
        )
        return record, notes

    def nodes(self, ctx: HarvestContext) -> list[ConstraintNode]:
        parents = projection_parents(ctx.layout)
        scopes = [RuleScope(ctx, None, parents)] + [RuleScope(ctx, b, parents) for b in ctx.layout.branches]
        return [node for scope in scopes for reader in self.readers for node in reader.read(scope)]

    @staticmethod
    def _own_defaults(ctx: HarvestContext) -> ParamsSnapshot:
        """The rule's own defaults: the values its saved text shows."""
        defaults = ctx.readings.default_params()
        own = defaults.rule_defaults.get(ctx.rule.ref)
        if own is None:
            return defaults
        return ParamsSnapshot(origin="rule_defaults", unit=defaults.unit, values=own)


def _divergence(saved: str, structural: str) -> str:
    """The lines of the saved text that the executed structure renders differently."""
    old_lines, new_lines = _lines(saved), _lines(structural)
    changes = []
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old = " / ".join(old_lines[i1:i2]) or "nothing"
        new = " / ".join(new_lines[j1:j2]) or "nothing"
        changes.append(f"the saved iseql_text has {old} where the executed structure renders {new}")
    return "; ".join(changes) or "the saved iseql_text differs from the executed structure in layout only"


def _lines(text: str) -> list[str]:
    """Lines of a rendered rule without indentation and opening brackets."""
    return [line.strip().removesuffix("(").strip() for line in text.splitlines() if line.strip()]


def _params_note(nodes: Sequence[ConstraintNode]) -> Note | None:
    """How the written parameters relate to the values in the SQL."""
    operators = [n for n in nodes if isinstance(n, TemporalOperatorNode)]
    if not operators:
        return None
    differing = []
    for node in operators:
        for p in node.payload.params:
            if p.name in ("ζ", "η") or p.value == p.engine_value:
                continue
            written = f"{p.raw} = {p.value}" if p.raw else f"{p.value}"
            differing.append(
                f"{node.constraint_id} {p.name}: written {written} {p.unit or ''}".rstrip()
                + f", passed to the SQL as {p.engine_value} and compared in {p.compare_domain}"
            )
    if not differing:
        return Note(
            code=NoteCode.PARAMS_UNIT,
            detail="every operator parameter is passed to the SQL with the value written in the rule",
        )
    return Note(
        code=NoteCode.PARAMS_UNIT,
        detail="detect_event converts parameters in seconds to frames (round(v · fps)) "
        "and the helpers apply int(); " + "; ".join(differing),
    )
