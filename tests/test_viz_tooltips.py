"""Unit tests for the unit tooltip contract (issue #24, render-opt).

`source_header` and `unit_tooltip` render the plain-text fields of the hover
card for one core unit row — markup lives in the static `DECK_TOOLTIP`
template, because Streamlit's deckgl frontend escapes interpolated values.
`attach_tooltips` decorates the render-opt pandas unit frame with those two
columns in one pass.  The generator and storage contracts differ by exactly
one line (storage capacity).  The tests pin the agreed rendering: titled
source, kW/kWh formatting, ISO dates ("active" when null), and the
state · district address with missing parts dropped.
"""

from datetime import date

import pandas as pd

from viz.tooltip import (
    DECK_TOOLTIP,
    area_card,
    attach_tooltips,
    source_header,
    unit_tooltip,
)


def generator_row(**overrides):
    row = {
        "unit_id": 1,
        "energy_source": "solar",
        "installed_capacity": 120.0,
        "commissioning_date": date(2015, 3, 1),
        "decommissioning_date": None,
        "longitude": 10.5,
        "latitude": 50.5,
        "state": "Bavaria",
        "region": "Upper Bavaria",
        "district": "Munich",
    }
    row.update(overrides)
    return row


def storage_row(**overrides):
    row = generator_row(energy_source="storage")
    row["storage_capacity"] = 800.0
    row.update(overrides)
    return row


class TestDeckTooltipTemplate:
    def test_template_references_the_decorated_plain_text_fields(self):
        assert "{source_header}" in DECK_TOOLTIP["html"]
        assert "{unit_body}" in DECK_TOOLTIP["html"]

    def test_template_itself_renders_the_markup(self):
        assert "<b>" in DECK_TOOLTIP["html"]
        assert "<br/>" in DECK_TOOLTIP["html"]


class TestGeneratorTooltip:
    def test_source_is_the_titled_header(self):
        assert source_header(generator_row()) == "Solar"

    def test_header_never_contains_markup(self):
        assert "<" not in source_header(generator_row())

    def test_installed_capacity_is_formatted_in_kw(self):
        text = unit_tooltip(generator_row(installed_capacity=1500.0))
        assert "Capacity: 1,500 kW" in text

    def test_capacity_is_an_integer_without_decimals(self):
        text = unit_tooltip(generator_row(installed_capacity=120.9))
        assert "Capacity: 121 kW" in text
        assert "120.9" not in text

    def test_commissioning_date_is_iso(self):
        assert "Commissioning: 2015-03-01" in unit_tooltip(generator_row())

    def test_decommissioning_date_is_active_when_null(self):
        assert "Decommissioning: active" in unit_tooltip(generator_row())

    def test_decommissioning_date_is_shown_when_set(self):
        text = unit_tooltip(generator_row(decommissioning_date=date(2020, 12, 31)))
        assert "Decommissioning: 2020-12-31" in text

    def test_location_joins_state_and_district(self):
        text = unit_tooltip(generator_row())
        assert "Bavaria · Munich" in text
        assert "district" not in text.lower()

    def test_missing_location_parts_are_dropped(self):
        text = unit_tooltip(generator_row(district=None))
        assert "Bavaria" in text
        assert " · " not in text


class TestStorageTooltip:
    def test_storage_advertises_storage_capacity_in_kwh(self):
        text = unit_tooltip(storage_row(storage_capacity=8000.0))
        assert "Storage: 8,000 kWh" in text

    def test_generators_never_show_a_storage_line(self):
        assert "kWh" not in unit_tooltip(generator_row())

    def test_storage_source_header_is_titled(self):
        assert source_header(storage_row()) == "Storage"


class TestTimestampTooltip:
    def test_timestamp_commissioning_renders_a_plain_iso_date(self):
        text = unit_tooltip(
            generator_row(commissioning_date=pd.Timestamp("2015-03-01"))
        )
        assert "Commissioning: 2015-03-01" in text
        assert "T00:00:00" not in text

    def test_nat_decommissioning_reads_active(self):
        text = unit_tooltip(generator_row(decommissioning_date=pd.NaT))
        assert "Decommissioning: active" in text

    def test_iso_string_dates_pass_through(self):
        text = unit_tooltip(generator_row(commissioning_date="2015-03-01"))
        assert "Commissioning: 2015-03-01" in text


class TestAttachTooltips:
    def test_adds_source_and_body_columns(self):
        frame = pd.DataFrame(
            [
                generator_row(),
                storage_row(energy_source="storage", storage_capacity=8000.0),
            ]
        )
        decorated = attach_tooltips(frame)
        assert list(decorated["source_header"]) == ["Solar", "Storage"]
        assert "Capacity: 120 kW" in decorated.loc[0, "unit_body"]
        assert "Storage: 8,000 kWh" in decorated.loc[1, "unit_body"]

    def test_leaves_the_original_columns_untouched(self):
        frame = pd.DataFrame([generator_row()])
        decorated = attach_tooltips(frame)
        assert "energy_source" in decorated.columns
        assert "installed_capacity" in decorated.columns
        assert "unit_id" in decorated.columns

    def test_missing_storage_column_skips_the_storage_line(self):
        frame = pd.DataFrame([generator_row()])
        assert "kWh" not in attach_tooltips(frame).loc[0, "unit_body"]

    def test_nan_storage_capacity_skips_the_storage_line(self):
        frame = pd.DataFrame(
            [storage_row(storage_capacity=float("nan"), energy_source="storage")]
        )
        assert "kWh" not in attach_tooltips(frame).loc[0, "unit_body"]

    def test_render_path_matches_the_row_contract(self):
        row = generator_row(decommissioning_date=date(2020, 12, 31))
        decorated = attach_tooltips(pd.DataFrame([row]))
        assert decorated.loc[0, "source_header"] == source_header(row)
        assert decorated.loc[0, "unit_body"] == unit_tooltip(row)

    def test_missing_dates_still_read_active_on_the_render_path(self):
        frame = pd.DataFrame([generator_row()])
        body = attach_tooltips(frame).loc[0, "unit_body"]
        assert "Commissioning: active" not in body  # commissioning date set
        assert "Decommissioning: active" in body


class TestAreaCard:
    def test_header_is_the_area_name(self):
        assert area_card("Berlin", 1200.0, 40)["source_header"] == "Berlin"

    def test_body_carries_capacity_in_mw(self):
        body = area_card("Berlin", 12345.6, 40)["unit_body"]
        assert "Capacity: 12,346 MW" in body
        assert "kW" not in body

    def test_body_carries_the_unit_count(self):
        assert "Units: 40" in area_card("Berlin", 1200.0, 40)["unit_body"]

    def test_header_and_body_fit_the_shared_deck_card(self):
        card = area_card("Berlin", 1200.0, 40)
        assert "{source_header}" in DECK_TOOLTIP["html"]
        assert "{unit_body}" in DECK_TOOLTIP["html"]
        assert card.keys() == {"source_header", "unit_body"}

    def test_unselected_area_carries_the_bare_name(self):
        card = area_card("Berlin", 1200.0, 40, selected=False)
        assert card == {"source_header": "Berlin", "unit_body": ""}