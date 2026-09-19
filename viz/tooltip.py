"""Unit tooltip rendering for the Streamlit viz app (issue #24).

One hover card per fetched unit row.  The generator and storage cards differ
by exactly one line (storage capacity, kWh).  Rows are decorated at fetch
time with two plain-text fields — the titled ``source_header`` and the
multi-line ``unit_body`` — that ``DECK_TOOLTIP`` interpolates.

The template carries all markup; the interpolated values must stay plain
text, because Streamlit's deckgl frontend HTML-escapes tooltip values before
inserting them — any markup in a value would render literally (the bug this
layout fixes).

``area_card`` (issue #26) builds a choropleth area's hover card in the same
two-field shape, so the identical ``DECK_TOOLTIP`` renders area hovers (name
over capacity/unit-count) with no per-layer tooltip switching.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from viz.header import format_mw, format_unit_count

# Deck-level tooltip template.  All HTML lives here; the {source_header} and
# {unit_body} values are escaped by the frontend before interpolation, so the
# body's newlines need `white-space: pre-line` to render as line breaks.
DECK_TOOLTIP: dict[str, str] = {
    "html": (
        "<b>{source_header}</b>"
        "<br/>"
        "<span style='white-space: pre-line;'>{unit_body}</span>"
    )
}


def _fmt_date(value: Any, *, fallback: str = "active") -> str:
    """ISO date for display; null/unknown values read as ``fallback`` (active)."""
    if isinstance(value, date):
        return value.isoformat()
    return fallback


def source_header(unit: Mapping[str, Any]) -> str:
    """Titled source label, e.g. ``"solar"`` -> ``"Solar"``."""
    return unit["energy_source"].title()


def unit_tooltip(unit: Mapping[str, Any]) -> str:
    """Multi-line hover-card body for one core unit row (plain text).

    Installed capacity (kW) always; storage capacity (kWh) only on storages;
    ISO commissioning/decommissioning dates ("active" when null); and the
    region · municipality address with missing parts dropped.
    Lines join with ``\n``; ``DECK_TOOLTIP`` renders them as line breaks.
    """
    parts = [f"Capacity: {unit['installed_capacity']:,.0f} kW"]
    if unit.get("storage_capacity") is not None:
        parts.append(f"Storage: {unit['storage_capacity']:,.0f} kWh")
    parts.append(f"Commissioning: {_fmt_date(unit['commissioning_date'])}")
    parts.append(f"Decommissioning: {_fmt_date(unit['decommissioning_date'])}")
    location = " · ".join(
        part for part in (unit["region"], unit["municipality"]) if part
    )
    if location:
        parts.append(location)
    return "\n".join(parts)


def area_card(name: str, capacity_mw: float, unit_count: int) -> dict[str, str]:
    """Hover-card fields for one choropleth area, in the unit card shape.

    Streamlit's deckgl interpolates a single ``DECK_TOOLTIP`` template per
    hovered object, so the area card must speak the same two plain-text fields
    the unit card uses: ``source_header`` (here the area name) and
    ``unit_body`` (the capacity in MW — matching the header metric — plus the
    unit count).  The template stays untouched; only the field values differ.
    """
    return {
        "source_header": name,
        "unit_body": (
            f"Capacity: {format_mw(capacity_mw)} MW\n"
            f"Units: {format_unit_count(unit_count)}"
        ),
    }
