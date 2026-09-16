"""Unit tests for the choropleth drill-down seam (issue #19).

Two seams are pinned against synthetic area names — no database, no Dash
runtime:

* ``plan_drill`` → the drill FILTER, metric-agnostic by construction.  Clicking
  an area at the active level produces the *same* child-level target (level +
  accumulated parent-chain filter) whether the visible value is the
  installed-capacity MW sum (default) or the unit count (toggle).  Both metrics
  therefore drive exactly the same area→child query: metric only changes the
  value expression, never the filter.

* ``drill_value`` → the VALUE expression, the only metric-aware seam.  Capacity
  MW (default) is ``SUM(installed_capacity) / 1000.0``; unit count (toggle) is
  ``COUNT(*)``.  The acceptance "for both metrics" is enforced here, where the
  two metrics legitimately differ.

``DrillFilter`` is immutable (frozen) so Dash's ``Input`` never mutates a chain
once planned.
"""

import pytest

from viz.drill import (
    DrillFilter,
    DrillValue,
    MAX_DRILL_LEVEL,
    drill_value,
    plan_drill,
)

HES = "Hessen"
KAS = "Kassel"
GUD = "Gudensberg"
SCHW = "Schwalm-Eder"

CAPACITY_MW = "installed_capacity_mw"
UNIT_COUNT = "unit_count"


# ------------------------------------------------------------------ #
#  Metric-agnostic drill filter                                       #
# ------------------------------------------------------------------ #


class TestDrillFilterIsMetricAgnostic:
    def test_region_click_targets_districts_for_both_metrics(self):
        cap = plan_drill(1, HES, CAPACITY_MW)
        count = plan_drill(1, HES, UNIT_COUNT)
        assert cap == DrillFilter(target_level=2, parent_filters={"region": HES})
        assert count == cap

    def test_district_click_targets_municipalities_for_both_metrics(self):
        cap = plan_drill(2, KAS, CAPACITY_MW, parent_chain=(("region", HES),))
        count = plan_drill(2, KAS, UNIT_COUNT, parent_chain=(("region", HES),))
        expected = DrillFilter(
            target_level=3,
            parent_filters={"region": HES, "district": KAS},
        )
        assert cap == expected
        assert count == expected

    def test_municipality_click_never_drills_for_both_metrics(self):
        chain = (("region", HES), ("district", KAS))
        assert plan_drill(3, GUD, CAPACITY_MW, parent_chain=chain) is None
        assert plan_drill(3, GUD, UNIT_COUNT, parent_chain=chain) is None

    def test_no_drill_past_level_three(self):
        chain = (("region", HES), ("district", KAS))
        assert plan_drill(3, SCHW, CAPACITY_MW, parent_chain=chain) is None
        assert plan_drill(3, SCHW, UNIT_COUNT, parent_chain=chain) is None

    def test_metric_never_enters_the_filter_build(self):
        # The metric only selects a VALUE expression; it can never be a filter
        # that would accidentally scope the child-level GROUP BY.
        cap = plan_drill(1, HES, CAPACITY_MW)
        assert "metric" not in cap.parent_filters
        assert "installed_capacity_mw" not in cap.parent_filters

    def test_parent_filter_is_immutable(self):
        drilled = plan_drill(2, KAS, CAPACITY_MW, parent_chain=(("region", HES),))
        with pytest.raises(TypeError):
            drilled.parent_filters["district"] = "Marburg"


# ------------------------------------------------------------------ #
#  Metric-aware value expression — the ONLY place metrics differ       #
# ------------------------------------------------------------------ #


class TestDrillValue:
    def test_capacity_mw_is_kilowatt_sum_to_megawatts(self):
        v = drill_value(CAPACITY_MW)
        assert v == DrillValue(value_expr="SUM(installed_capacity) / 1000.0", unit="MW")

    def test_unit_count_is_a_row_count(self):
        v = drill_value(UNIT_COUNT)
        assert v == DrillValue(value_expr="COUNT(*)", unit="unit")

    def test_metrics_are_not_the_same_expression(self):
        assert drill_value(CAPACITY_MW) != drill_value(UNIT_COUNT)

    def test_unknown_metric_is_rejected(self):
        with pytest.raises(ValueError):
            drill_value("watts_per_capita")


# ------------------------------------------------------------------ #
#  Drill level ceiling                                                #
# ------------------------------------------------------------------ #


class TestDrillCeiling:
    def test_max_drill_level_is_three(self):
        assert MAX_DRILL_LEVEL == 3

    def test_drilling_below_three_is_always_allowed_for_both_metrics(self):
        assert plan_drill(1, HES, CAPACITY_MW) == DrillFilter(
            target_level=2, parent_filters={"region": HES}
        )
        assert plan_drill(2, KAS, UNIT_COUNT, parent_chain=(("region", HES),)) == (
            DrillFilter(
                target_level=3,
                parent_filters={"region": HES, "district": KAS},
            )
        )
