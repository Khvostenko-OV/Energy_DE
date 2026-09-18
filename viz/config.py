"""Configuration defaults for the Streamlit + PyDeck visualization app (issue #23).

Single home for the T1 tracer's user-facing defaults: the active-units
timescope window, the checked source set, the initial drill level, the CARTO
Light basemap style, and the Germany-overview view state.  Widgets in
`viz.app` seed from these, so a default exists exactly once.
"""

from __future__ import annotations

from datetime import date

# Sidebar chooser order, topmost level first.  The drill levels mirror the
# spatial progression of `etl.db_schema.BOUNDARY_LEVEL_COLUMNS` (region,
# district, municipality) under the country overview.
MAP_LEVELS = ("Germany", "Regions", "Districts", "Municipalities")

# The drill level selected on first run.
INITIAL_LEVEL = "Germany"

# Per-source sidebar checkboxes in canonical display order — the six loaded
# sources, generators first (bio → wind) then storage.  All checked by default.
DEFAULT_SOURCES = ("bio", "gas", "hydro", "solar", "wind", "storage")

# Active-units timescope default: every unit commissioned up to today counts,
# and nothing is excluded for decommissioning before the epoch default.
TIMESCOPE_START = date(1900, 1, 1)


def default_timescope() -> tuple[date, date]:
    """The default active-units window: ``1900-01-01`` to today."""
    return (TIMESCOPE_START, date.today())


# CARTO Light (Positron GL) basemap style, reachable without a style token.
LIGHT_MAP_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"

# Chooser label → style URL.  Satellite / Topographic styles join later;
# today "Light" is the single (and default) entry.
MAP_STYLES = {"Light": LIGHT_MAP_STYLE}

# Default viewport for the country overview.
GERMANY_CENTER = {"lon": 10.4, "lat": 51.1}
INITIAL_ZOOM = 5.2
