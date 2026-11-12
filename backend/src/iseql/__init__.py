"""ISEQL engine: parse ISEQL query text and compile event models to SQL.

- ``helpers``  operator definitions + SQL rendering (single source of truth)
- ``parser``   ISEQL text -> model
- ``compiler`` model -> SQL (+ ISEQL text rendering)
- ``facade``   thin entry points for the service/API layers
"""
from iseql.facade import (
    compile_event,
    compile_event_plan,
    compile_model,
    compile_query,
    render_model,
    validate_model,
    vocabulary,
)

__all__ = [
    "compile_event",
    "compile_event_plan",
    "compile_model",
    "compile_query",
    "render_model",
    "validate_model",
    "vocabulary",
]
