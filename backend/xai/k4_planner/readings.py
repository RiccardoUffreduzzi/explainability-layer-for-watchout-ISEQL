"""The parameter readings of a temporal operator, chosen on the engine's value.

For each threshold ``δ`` or ``ε`` the reading of the glossary entry of the operator with
condition ``<param> = ∞`` (``engine_value`` is ``inf``) or ``<param> = d`` 
(a number rendered through ``value_ref``). 
"""

import re
from dataclasses import dataclass
from typing import Final

from xai.contract.ids import term_id
from xai.contract.model import TemporalOperatorNode
from xai.contract.plan import PlanNote, PlanNoteCode, Reading, UnmatchedReading
from xai.k4_planner.view import SourceOfTruthView

READING_CONDITION: Final = re.compile(r"^(δ|ε) = (∞|d)$")
"""Grammar of the conditions of the glossary readings"""

INFINITE = "inf"
"""threshold without limit."""


@dataclass(frozen=True)
class ReadingChoice:
    readings: tuple[Reading, ...]
    unmatched: tuple[UnmatchedReading, ...]
    notes: tuple[PlanNote, ...]


def reading_condition(param: str, engine_value: object) -> str:
    """``δ = ∞`` for an unlimited threshold, ``δ = d`` for a number"""
    return f"{param} = {'∞' if engine_value == INFINITE else 'd'}"


def choose_readings(view: SourceOfTruthView, node: TemporalOperatorNode) -> ReadingChoice:
    entry = view.term(term_id("operator", node.payload.name))
    phrases = {reading.condition: reading.phrase for reading in entry.parameter_readings or ()}
    readings: list[Reading] = []
    unmatched: list[UnmatchedReading] = []
    notes: list[PlanNote] = []
    for position, param in enumerate(node.payload.params):
        name = param.name
        if name == "δ" or name == "ε":
            condition = reading_condition(name, param.engine_value)
            phrase = phrases.get(condition)
            if phrase is None:
                unmatched.append(UnmatchedReading(constraint_id=node.constraint_id, param=name))
                continue
            value_ref = (
                None
                if param.engine_value == INFINITE
                else view.pointer(node.constraint_id, "payload", "params", position, "engine_value")
            )
            readings.append(Reading(param=name, condition=condition, phrase=phrase, value_ref=value_ref))
        elif name == "ρ" and param.engine_value != 0:
            notes.append(
                PlanNote(
                    code=PlanNoteCode.RHO_NOT_ZERO, detail=f"{node.constraint_id}: ρ = {param.engine_value}"
                )
            )
    return ReadingChoice(readings=tuple(readings), unmatched=tuple(unmatched), notes=tuple(notes))
