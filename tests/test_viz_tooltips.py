"""Unit tests for the unit tooltip contract (issue #24).

`unit_tooltip` renders the hover card for one core unit row.  The generator
and storage contracts differ by exactly one line (storage capacity).  The
tests pin the agreed rendering: titled source, kW/kWh formatting, ISO dates
("active" when null), and the region · district · municipality address with
missing parts dropped.
"""

from datetime import date

from viz.tooltip import unit_tooltip


def generator_row(**overrides):
    row = {
        "unit_id": 1,
        "energy_source": "solar",
        "installed_capacity": 120.0,
        "commissioning_date": date(2015, 3, 1),
        "decommissioning_date": None,
        "longitude": 10.5,
        "latitude": 50.5,
        "region": "Bavaria",
        "district": "Munich district",
        "municipality": "Munich",
    }
    row.update(overrides)
    return row


def storage_row(**overrides):
    row = generator_row(energy_source="storage")
    row["storage_capacity"] = 800.0
    row.update(overrides)
    return row


class TestGeneratorTooltip:
    def test_source_is_the_titled_header(self):
        assert unit_tooltip(generator_row()).startswith("<b>Solar</b>")

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

    def test_location_joins_region_district_municipality(self):
        text = unit_tooltip(generator_row())
        assert "Bavaria · Munich district · Munich" in text

    def test_missing_location_parts_are_dropped(self):
        text = unit_tooltip(generator_row(district=None, municipality=None))
        assert "Bavaria" in text
        assert " · " not in text


class TestStorageTooltip:
    def test_storage_advertises_storage_capacity_in_kwh(self):
        text = unit_tooltip(storage_row(storage_capacity=8000.0))
        assert "Storage: 8,000 kWh" in text

    def test_generators_never_show_a_storage_line(self):
        assert "kWh" not in unit_tooltip(generator_row())

    def test_storage_source_header_is_titled(self):
        assert unit_tooltip(storage_row()).startswith("<b>Storage</b>")
