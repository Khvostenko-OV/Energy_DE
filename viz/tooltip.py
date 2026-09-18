"""Unit tooltip rendering for the Streamlit viz app (issue #24).

One hover card per fetched unit row.  The rendering is a pure function of the
row dict: the generator and storage cards differ by exactly one line (storage
capacity, kWh).  Rows are decorated with their ``tooltip`` string at fetch
time, and the deck points every layer at that field via ``DECK_TOOLTIP``.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

# Deck-level tooltip template: every layer's rows carry their own pre-rendered
# ``tooltip`` string, so one template serves generators and storages alike.
DECK_TOOLTIP: dict[str, str] = {"html": "{tooltip}"}


def _fmt_date(value: Any, *, fallback: str = "active") -> str:
    """ISO date for display; null/unknown values read as ``fallback`` (active)."""
    if isinstance(value, date):
        return value.isoformat()
    return fallback


def unit_tooltip(unit: Mapping[str, Any]) -> str:
    """Hover card for one core unit row (generator or storage).

    Source and installed capacity (kW) always; storage capacity (kWh) only on
    storages; ISO commissioning/decommissioning dates ("active" when null);
    and the region · district · municipality address with missing parts
    dropped.  Lines join with ``<br/>`` so the card renders in pydeck's html
    tooltip.
    """
    parts = [
        f"<b>{unit['energy_source'].title()}</b>",
        f"Capacity: {unit['installed_capacity']:,.0f} kW",
    ]
    if unit.get("storage_capacity") is not None:
        parts.append(f"Storage: {unit['storage_capacity']:,.0f} kWh")
    parts.append(f"Commissioning: {_fmt_date(unit['commissioning_date'])}")
    parts.append(f"Decommissioning: {_fmt_date(unit['decommissioning_date'])}")
    location = " · ".join(
        part for part in (unit["region"], unit["district"], unit["municipality"]) if part
    )
    if location:
        parts.append(location)
    return "<br/>".join(parts)
