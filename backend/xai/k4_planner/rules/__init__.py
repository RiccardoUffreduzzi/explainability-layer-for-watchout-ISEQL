"""The translation rules, one per kind of rule node, and their registry (§4 of the use cases)."""

from collections.abc import Mapping
from typing import Final

from xai.k4_planner.rules.base import RuleContext, RuleResult, TranslationRule
from xai.k4_planner.rules.comparison import AttributeComparisonRule, IdentityRule
from xai.k4_planner.rules.duration import DurationRule
from xai.k4_planner.rules.operator import TemporalOperatorRule
from xai.k4_planner.rules.projection import ProjectionRule
from xai.k4_planner.rules.selection import SelectionRule

RULES: Final[Mapping[str, TranslationRule]] = {
    "selection": SelectionRule(),
    "temporal_operator": TemporalOperatorRule(),
    "identity": IdentityRule(),
    "attribute_comparison": AttributeComparisonRule(),
    "duration": DurationRule(),
    "projection": ProjectionRule(),
}
"""``kind`` -> its rule. ``set_operation`` has none: ``choose_branches`` excludes it (K4-A8)."""

__all__ = ["RULES", "RuleContext", "RuleResult", "TranslationRule"]
