"""ISEQL+ operator definitions and SQL rendering (single source of truth).

This module owns everything about the temporal operators:
  - the operator set (``OPERATORS``) and which δ/ε thresholds each uses
    (``OPERATOR_PARAMS``),
  - the full threshold parameter set (``ALL_PARAMS``) and strictness operators,
  - the interval model + operator detection (``detect_operator`` /
    ``apply_manual_override``),
  - the SQL rendering functions (``iseql_before`` ... ``iseql_after``) and the
    ``OPERATOR_HELPERS`` map.

The ISEQL parser and compiler import from here rather than re-defining these.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# operator definitions
# ---------------------------------------------------------------------------

OPERATORS = ("Bef", "Aft", "SP", "EF", "DJ", "RDJ", "LOJ", "ROJ")

# Which temporal thresholds (δ/ε) each operator uses.
OPERATOR_PARAMS: dict[str, tuple[str, ...]] = {
    "Bef": ("delta",),
    "Aft": ("delta",),
    "SP": ("delta",),
    "EF": ("epsilon",),
    "DJ": ("delta", "epsilon"),
    "RDJ": ("delta", "epsilon"),
    "LOJ": ("delta", "epsilon"),
    "ROJ": ("delta", "epsilon"),
}

# Full threshold parameter set per operator pair.
ALL_PARAMS = ("delta", "epsilon", "zeta", "eta", "rho")

STRICTNESS_OPERATORS = ("<=", "<", ">=", ">")


def _strictness_op(op: str) -> str:
    if op not in STRICTNESS_OPERATORS:
        raise ValueError(
            f"invalid strictness operator '{op}'; expected one of {sorted(STRICTNESS_OPERATORS)}"
        )
    return op


# ---------------------------------------------------------------------------
# interval model + operator detection
# ---------------------------------------------------------------------------

@dataclass
class Predicate:
    name: str
    arguments: list[str] = field(default_factory=list)


@dataclass
class Interval:
    pred: Predicate
    Ts: int
    Te: int

    def __post_init__(self):
        if self.Ts > self.Te:
            raise ValueError(f"Ts ({self.Ts}) must be <= Te ({self.Te})")


@dataclass
class DetectionResult:
    operator: str
    delta: Optional[int] = None
    epsilon: Optional[int] = None


def detect_operator(r: Interval, s: Interval) -> DetectionResult:
    """Auto-detect the most specific ISEQL operator for (r, s); r is first."""
    rTs, rTe, sTs, sTe = r.Ts, r.Te, s.Ts, s.Te
    if rTe <= sTs:
        return DetectionResult("Bef", delta=sTs - rTe)
    if sTe <= rTs:
        return DetectionResult("Aft", delta=rTs - sTe)
    if sTs <= rTs and rTe <= sTe:
        return DetectionResult("DJ", delta=rTs - sTs, epsilon=sTe - rTe)
    if rTs <= sTs and sTe <= rTe:
        return DetectionResult("RDJ", delta=sTs - rTs, epsilon=rTe - sTe)
    if rTs <= sTs < rTe and rTe <= sTe:
        return DetectionResult("LOJ", delta=sTs - rTs, epsilon=sTe - rTe)
    if sTs <= rTs < sTe and sTe <= rTe:
        return DetectionResult("ROJ", delta=rTs - sTs, epsilon=rTe - sTe)
    return DetectionResult("UNKNOWN")


def apply_manual_override(operator: str, r: Interval, s: Interval) -> DetectionResult:
    """Declassify an overlapping pair to SP or EF (never auto-detected)."""
    if operator == "SP":
        return DetectionResult("SP", delta=(s.Ts - r.Ts) if r.Ts <= s.Ts else 0)
    if operator == "EF":
        return DetectionResult("EF", epsilon=(r.Te - s.Te) if s.Te <= r.Te else 0)
    return detect_operator(r, s)


# ---------------------------------------------------------------------------
# SQL rendering
# ---------------------------------------------------------------------------

def iseql_before(r: str, s: str, delta: Optional[int | str] = None,
                 zeta: str = "<=", rho: int | str = 0,
                 cols: tuple[str, str] = ("sf", "ef")) -> str:
    """ISEQL+ Before (Bef): r.Te ζ (s.Ts + ρ)  ∧  (s.Ts - r.Te) <= δ + ρ.
    ζ ∈ {⩽, <} is the left strictness; default non-strict (⩽) makes touching intervals
    (gap 0) valid. ρ is the robustness tolerance, default 0. δ unbounded (∞) when omitted.
    ``cols`` = (start_column, end_column): frames (``sf``/``ef``) or time (``st``/``et``)."""
    cst, ced = cols
    rho = int(rho or 0)
    z = _strictness_op(zeta)
    if delta is None:
        return f"({r}.{ced} {z} ({s}.{cst} + {rho}))"
    delta = int(delta)
    return (
        f"({r}.{ced} {z} ({s}.{cst} + {rho}) "
        f"AND ({s}.{cst} - {r}.{ced}) <= {delta + rho})"
    )


def iseql_loj(
    r: str,
    s: str,
    delta: Optional[int | str] = None,
    epsilon: Optional[int | str] = None,
    zeta: str = "<=",
    eta: str = "<=",
    rho: int | str = 0,
    cols: tuple[str, str] = ("sf", "ef"),
) -> str:
    """ISEQL+ Left Overlap Join (LOJ):
    (r.Ts - ρ) ζ s.Ts  ∧  s.Ts < r.Te + ρ  ∧  (s.Ts - ρ) < r.Te
    ∧  r.Te η (s.Te + ρ)  ∧  (s.Ts - r.Ts) <= δ + ρ  ∧  (s.Te - r.Te) <= ε + ρ."""
    cst, ced = cols
    z = _strictness_op(zeta)
    n = _strictness_op(eta)
    rho = int(rho or 0)
    parts = [
        f"({r}.{cst} - {rho}) {z} {s}.{cst}",
        f"{s}.{cst} < ({r}.{ced} + {rho})",
        f"({s}.{cst} - {rho}) < {r}.{ced}",
        f"{r}.{ced} {n} ({s}.{ced} + {rho})",
    ]
    if delta is not None:
        delta = int(delta)
        parts.append(f"({s}.{cst} - {r}.{cst}) <= {delta + rho}")
    if epsilon is not None:
        epsilon = int(epsilon)
        parts.append(f"({s}.{ced} - {r}.{ced}) <= {epsilon + rho}")
    return f"({' AND '.join(parts)})"


def iseql_sp(
    r: str,
    s: str,
    delta: Optional[int | str] = None,
    zeta: str = "<=",
    rho: int | str = 0,
    cols: tuple[str, str] = ("sf", "ef"),
) -> str:
    """ISEQL+ Start Preceding (SP):
    (r.Ts - ρ) ζ s.Ts  ∧  s.Ts < r.Te + ρ  ∧  (s.Ts - r.Ts) <= δ + ρ."""
    cst, ced = cols
    z = _strictness_op(zeta)
    rho = int(rho or 0)
    parts = [
        f"({r}.{cst} - {rho}) {z} {s}.{cst}",
        f"{s}.{cst} < ({r}.{ced} + {rho})",
    ]
    if delta is not None:
        delta = int(delta)
        parts.append(f"({s}.{cst} - {r}.{cst}) <= {delta + rho}")
    return f"({' AND '.join(parts)})"


def iseql_dj(
    r: str,
    s: str,
    delta: Optional[int | str] = None,
    epsilon: Optional[int | str] = None,
    zeta: str = "<=",
    eta: str = "<=",
    rho: int | str = 0,
    cols: tuple[str, str] = ("sf", "ef"),
) -> str:
    """ISEQL+ During Join (DJ): r is contained within s."""
    cst, ced = cols
    z = _strictness_op(zeta)
    n = _strictness_op(eta)
    rho = int(rho or 0)
    parts = [
        f"({s}.{cst} - {rho}) {z} {r}.{cst}",
        f"{r}.{cst} <= ({s}.{ced} + {rho})",
        f"({s}.{cst} - {rho}) <= {r}.{ced}",
        f"{r}.{ced} {n} ({s}.{ced} + {rho})",
    ]
    if delta is not None:
        delta = int(delta)
        parts.append(f"({r}.{cst} - {s}.{cst}) <= {delta + rho}")
    if epsilon is not None:
        epsilon = int(epsilon)
        parts.append(f"({s}.{ced} - {r}.{ced}) <= {epsilon + rho}")
    return f"({' AND '.join(parts)})"


def iseql_ef(
    r: str,
    s: str,
    epsilon: Optional[int | str] = None,
    eta: str = "<=",
    rho: int | str = 0,
    cols: tuple[str, str] = ("sf", "ef"),
) -> str:
    """ISEQL+ End Following (EF)."""
    cst, ced = cols
    n = _strictness_op(eta)
    rho = int(rho or 0)
    parts = [
        f"({r}.{cst} - {rho}) < {s}.{ced}",
        f"{s}.{ced} {n} ({r}.{ced} + {rho})",
    ]
    if epsilon is not None:
        epsilon = int(epsilon)
        parts.append(f"({r}.{ced} - {s}.{ced}) <= {epsilon + rho}")
    return f"({' AND '.join(parts)})"


def iseql_roj(
    r: str,
    s: str,
    delta: Optional[int | str] = None,
    epsilon: Optional[int | str] = None,
    zeta: str = "<=",
    eta: str = "<=",
    rho: int | str = 0,
    cols: tuple[str, str] = ("sf", "ef"),
) -> str:
    """ISEQL+ Right Overlap Join (ROJ): reverse of LOJ (arguments swapped)."""
    return iseql_loj(s, r, delta, epsilon, zeta, eta, rho, cols)


def iseql_rdj(
    r: str,
    s: str,
    delta: Optional[int | str] = None,
    epsilon: Optional[int | str] = None,
    zeta: str = "<=",
    eta: str = "<=",
    rho: int | str = 0,
    cols: tuple[str, str] = ("sf", "ef"),
) -> str:
    """ISEQL+ Reverse During Join (RDJ): reverse of DJ (arguments swapped)."""
    return iseql_dj(s, r, delta, epsilon, zeta, eta, rho, cols)


def iseql_after(r: str, s: str, delta: Optional[int | str] = None,
                zeta: str = "<=", rho: int | str = 0,
                cols: tuple[str, str] = ("sf", "ef")) -> str:
    """ISEQL+ After (Aft): reverse of Bef (arguments swapped)."""
    return iseql_before(s, r, delta, zeta, rho, cols)


# operator -> (SQL function, temporal thresholds)
OPERATOR_HELPERS = {
    "Bef": (iseql_before, OPERATOR_PARAMS["Bef"]),
    "Aft": (iseql_after, OPERATOR_PARAMS["Aft"]),
    "SP": (iseql_sp, OPERATOR_PARAMS["SP"]),
    "EF": (iseql_ef, OPERATOR_PARAMS["EF"]),
    "DJ": (iseql_dj, OPERATOR_PARAMS["DJ"]),
    "RDJ": (iseql_rdj, OPERATOR_PARAMS["RDJ"]),
    "LOJ": (iseql_loj, OPERATOR_PARAMS["LOJ"]),
    "ROJ": (iseql_roj, OPERATOR_PARAMS["ROJ"]),
}


def sql_threshold(name: str, value):
    """A threshold as the helpers above write it into the SQL.

    δ and ε are cast with ``int()`` (None = unbounded), ρ is
    ``int(ρ or 0)``, ζ and η are written as given.
    """
    if name in ("zeta", "eta"):
        return value
    if name == "rho":
        return int(value or 0)
    return None if value is None else int(value)
