"""Curated visual constants for the map, choropleth, and charts (issue #18).

Single shared home for the energy-source color palette and marker symbol used
by the Dash scatter map — and, later, the choropleth fills and the chart strip
(issues #19/#20).  Keys are the canonical lowercase ``energy_source`` values
stored in core; the HTML hex values are chosen to stay distinguishable on the
open-street-map basemap.  Categories not present in the loaded data (diesel,
from the not-yet-loaded cogeneration source) still get a slot so this is the
complete fixed mapping every downstream layer reuses.
"""

# Canonical energy_source → hex color.  "storage" is a full category here even
# though core stores it separately from the five generator sources, so charts
# and the choropleth can key on the same mapping.
ENERGY_COLORS = {
    "bio": "#43a047",
    "gas": "#ef6c00",
    "hydro": "#1e88e5",
    "solar": "#fdd835",
    "wind": "#00897b",
    "diesel": "#6d4c41",
    "storage": "#4e342e",
}

# Fallback injected color for an energy_source outside ENERGY_COLORS, so an
# unexpected source still renders instead of crashing the figure builder.
DEFAULT_COLOR = "#9e9e9e"

# Map marker symbol.  "circle" is deliberate: plotly's scattermap (MapLibre)
# only honors marker.color for circle symbols — non-circle Maki icons load as
# un-tinted SVGs (and diamond isn't even in the Maki 2.1 set plotly.js ships),
# so a shape-based storage distinction would silently drop the storage color.
# Storages instead differ by color (#4e342e dark brown).
MARKER_SYMBOL = "circle"

# Sequential fill color scale for the choropleth drill layer (issue #19).
# A warm-to-cool single-hue ramp keeps the filled areas legible beneath the
# energy-source scatter markers; the choropleth trace is shared by both
# metrics, so this palette is metric-agnostic too.
CHOROPLETH_COLORSCALE = "YlGnBu"

# Source paint order, bottom of the layer stack first.  Plotly draws later
# traces over earlier ones, so storage goes in first and the read across the
# stack (bottom → top) is storage, wind, solar, hydro, gas, bio — bio on the
# very top.  The map legend renders this list reversed, so the sidebar reads
# bio down to storage.  Sources outside this list (an unexpected energy_source)
# are appended last so they still paint above everything and stay visible.
SOURCE_LAYER_ORDER = ("storage", "wind", "solar", "hydro", "gas", "bio")