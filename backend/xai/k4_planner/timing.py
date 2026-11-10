"""The ``t_order`` of a step that comes after others: the latest of theirs."""

from collections.abc import Iterable, Mapping

from xai.contract.plan import TOrderBasis


def latest_t_order(
    depends_on: Iterable[str],
    t_orders: Mapping[str, float | None],
) -> tuple[float | None, TOrderBasis]:
    """The largest known ``t_order`` among the steps this one depends on.

    ``interval`` when there is one, ``none`` when none of them is placed in time.
    """
    known = [t for t in (t_orders[step_id] for step_id in depends_on) if t is not None]
    if not known:
        return None, TOrderBasis.NONE
    return max(known), TOrderBasis.INTERVAL
