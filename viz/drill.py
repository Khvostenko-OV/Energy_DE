"""Choropleth drill-down seam (issue #19).

Split along the acceptance's own axis:

* ``plan_drill`` — the drill FILTER, metric-agnostic by construction (it takes
  no metric at all).  Clicking an area at the active boundary level produces
  the child-level target (target level + accumulated parent-name chain)
  regardless of the visible value — installed-capacity MW sum (default) or
  unit count (toggle).  The metric never enters the filter map: it only picks
  the value expression (``drill_value``).  This is what makes the area→child
  query correct *for both metrics* — the filter is shared, only the value
  differs.

* ``drill_value`` — the VALUE expression, the only metric-aware seam.  Capacity
  MW (default) is the installed-capacity kilowatt sum scaled to megawatts;
  unit count (toggle) is a row count.

``DrillFilter`` is immutable (frozen) so a planned chain can never be mutated
by a later Dash ``Input``.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from etl.db_schema import BOUNDARY_LEVEL_COLUMNS

MAX_DRILL_LEVEL = 3

CAPACITY_MW = "installed_capacity_mw"
UNIT_COUNT = "unit_count"

METRIC_UNITS = {
    CAPACITY_MW: "MW",
    UNIT_COUNT: "unit",
}
VALUE_EXPRESSIONS = {
    CAPACITY_MW: "SUM(installed_capacity) / 1000.0",
    UNIT_COUNT: "COUNT(*)",
}


@dataclass(frozen=True)
class DrillFilter:
    """A metric-agnostic child-level query scope.

    ``target_level`` is the boundary level the child query runs at;
    ``parent_filters`` is the FULL accumulated parent-name chain (region →
    region+district) that scopes the child query, so repeated district /
    municipality names never collide across parents.  Immutable, so Dash's
    ``Input`` can never mutate a chain once planned.
    """

    target_level: int
    parent_filters: Mapping


@dataclass(frozen=True)
class DrillValue:
    """The metric-aware value expression and its display unit."""

    value_expr: str
    unit: str


def plan_drill(active_level, clicked_area_name, parent_chain=()):
    """Map a click at ``active_level`` to the next level's query scope.

    Returns ``None`` (re-center, no drill) at the max drill level.  The FILTER
    is metric-agnostic: the metric only picks a value expression later.
    """
    if active_level >= MAX_DRILL_LEVEL:
        return None
    parent_filters_by_column = dict(parent_chain)
    parent_filters_by_column[BOUNDARY_LEVEL_COLUMNS[active_level]] = clicked_area_name
    return DrillFilter(
        target_level=active_level + 1,
        parent_filters=MappingProxyType(parent_filters_by_column),
    )


def drill_value(metric):
    """The metric-aware value seam: expression + unit for ``metric``."""
    try:
        value_expr = VALUE_EXPRESSIONS[metric]
    except KeyError:
        raise ValueError(f"unknown metric: {metric!r}") from None
    return DrillValue(value_expr=value_expr, unit=METRIC_UNITS[metric])
