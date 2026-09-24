"""Curated visual constants for the Streamlit + PyDeck map (issue #23).

Single shared home for the energy-source color palette and the canonical
layer order used by the map's unit layers.  Keys are the canonical
lowercase ``energy_source`` values stored in core; the hex values are chosen
to stay distinguishable on the Light (Positron) basemap.  Categories not yet
present in the loaded data (diesel, from the not-yet-loaded cogeneration
source) still get a slot so this is the complete fixed mapping every
downstream layer reuses.
"""

from __future__ import annotations

# Canonical energy_source → hex color.  "storage" is a full category here even
# though core stores it separately from the five generator sources.
ENERGY_COLORS = {
    "bio": "#43a047",
    "gas": "#ef6c00",
    "hydro": "#0d47a1",
    "solar": "#fdd835",
    "wind": "#9c27b0",
    "diesel": "#6d4c41",
    "storage": "#4e342e",
}

# Fallback injected color for an energy_source outside ENERGY_COLORS, so an
# unexpected source still renders instead of crashing the map builder.
DEFAULT_COLOR = "#9e9e9e"


def source_color(source: str) -> str:
    """Hex color for an energy_source, falling back to ``DEFAULT_COLOR``."""
    return ENERGY_COLORS.get(source, DEFAULT_COLOR)

# Source paint order, bottom of the layer stack first.  The map's unit
# layers paint in this order (storage at the very bottom, bio on the very
# top); the sidebar's checkboxes read it reversed, so the sidebar lists bio
# down to storage.  Sources outside this list are appended last so they still
# paint above everything and stay visible.
SOURCE_LAYER_ORDER = ("storage", "wind", "solar", "hydro", "gas", "bio")
