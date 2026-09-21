"""Unit tooltip rendering for the Streamlit viz app (issue #24, render-opt).

One hover card per fetched unit row.  The generator and storage cards differ
by exactly one line (storage capacity, kWh).  `attach_tooltips` decorates the
render-opt pandas unit frame at fetch time with two plain-text fields — the
titled ``source_header`` and the multi-line ``unit_body`` — that
``DECK_TOOLTIP`` interpolates.

The template carries all markup; the interpolated values must stay plain
text, because Streamlit's deckgl frontend HTML-escapes tooltip values before
inserting them — any markup in a value would render literally (the bug this
layout fixes).

``area_card`` (issue #26) builds a choropleth area's hover card in the same
two-field shape, so the identical ``DECK_TOOLTIP`` renders area hovers (name
over capacity/unit-count) with no per-layer tooltip switching.  Unselected
areas (outlined for context, render-opt) render the bare name with an empty
body, so their card never fakes a capacity figure.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

import pandas as pd

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
    """ISO date for display; null/unknown values read as ``fallback`` (active).

    Accepts ``datetime.date`` objects (DB rows), pandas ``Timestamp`` values
    (the raw render-opt unit frame) and the ISO date strings the frame
    normalizes to before pydeck serialization.
    """
    if _missing(value):
        return fallback
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return fallback


def _missing(value: Any) -> bool:
    """Whether a cell is absent: ``None``, pandas ``NaN``/``NaT``, ``pd.NA``.

    The render-opt unit frame hands SQL NULLs back as ``NaN``/``NaT``, while
    the old row fetches handed them back as ``None`` — both must read as
    "missing" for the hover card.
    """
    return value is None or bool(pd.isna(value))


def source_header(unit: Mapping[str, Any]) -> str:
    """Titled source label, e.g. ``"solar"`` -> ``"Solar"``."""
    return unit["energy_source"].title()


def unit_tooltip(unit: Mapping[str, Any]) -> str:
    """Multi-line hover-card body for one core unit row (plain text).

    Installed capacity (kW) always; storage capacity (kWh) only on storages;
    ISO commissioning/decommissioning dates ("active" when null); and the
    state · district address with missing parts dropped.
    Lines join with ``\n``; ``DECK_TOOLTIP`` renders them as line breaks.
    """
    parts = [f"Capacity: {unit['installed_capacity']:,.0f} kW"]
    if not _missing(unit.get("storage_capacity")):
        parts.append(f"Storage: {unit['storage_capacity']:,.0f} kWh")
    parts.append(f"Commissioning: {_fmt_date(unit['commissioning_date'])}")
    parts.append(f"Decommissioning: {_fmt_date(unit['decommissioning_date'])}")
    location = " · ".join(
        part for part in (unit["state"], unit["district"]) if not _missing(part)
    )
    if location:
        parts.append(location)
    return "\n".join(parts)


def attach_tooltips(units: pd.DataFrame) -> pd.DataFrame:
    """Add the two hover-card columns to the render-opt unit frame.

    ``source_header`` and ``unit_body`` per row come straight from
    `source_header` and `unit_tooltip` — the card contract this module
    documents — so ``attach_tooltips`` adapts the pandas frame for them
    (one dict per row via ``itertuples``) instead of re-formatting the card
    a second time.  The frame keeps every original column, so the scatter
    layers still carry the raw values alongside the decorated ones.
    """
    out = units.copy()
    headers: list[str] = []
    bodies: list[str] = []
    for row in out.itertuples(index=False):
        record = row._asdict()
        headers.append(source_header(record))
        bodies.append(unit_tooltip(record))
    out["source_header"] = headers
    out["unit_body"] = bodies
    return out


def area_card(
    name: str, capacity_mw: float, unit_count: int, *, selected: bool = True
) -> dict[str, str]:
    """Hover-card fields for one choropleth area, in the unit card shape.

    Streamlit's deckgl interpolates a single ``DECK_TOOLTIP`` template per
    hovered object, so the area card must speak the same two plain-text fields
    the unit card uses: ``source_header`` (here the area name) and
    ``unit_body`` (the capacity in MW — matching the header metric — plus the
    unit count).  The template stays untouched; only the field values differ.

    An unselected area (render-opt: the layer outlines the whole level but
    fills only the picked areas) carries the bare name and an empty body, so
    its card shows no fabricated capacity/count.
    """
    if not selected:
        return {"source_header": name, "unit_body": ""}
    return {
        "source_header": name,
        "unit_body": (
            f"Capacity: {format_mw(capacity_mw)} MW\n"
            f"Units: {format_unit_count(unit_count)}"
        ),
    }