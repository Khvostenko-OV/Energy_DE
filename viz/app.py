"""Streamlit entrypoint for the German Energy Units map (issues #23-#25).

T2 (#24): renders one scatter layer per checked energy source with
active-units timescope filtering, a sidebar check-all toggle, per-source
checkboxes, a date-range timescope, and a hover card for every unit.

T3 (#25): a live header above the map.  The header shows the active drill
level and the count of displayed areas — or the single area's name when
exactly one area is shown (e.g. "Region Berlin") — plus total installed
capacity (MW), the active-unit count, and the displayed area in km².  All
figures recompute on every rerun (source/timescope/level changes) and pull
from the same predicate the map renders.

T1 tracer (#23): when the core tables are absent — or the database is
unreachable — the app hides the data widgets and shows only a full-width
"No core tables" notice plus the empty basemap deck.  Widget defaults come
from `viz.config`, the deck from `viz.map_builder`, the fetch from `viz.data`,
the tooltip from `viz.tooltip`, and the header strings from `viz.header`.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

# Streamlit adds only this script's folder to sys.path, so the repo root
# wouldn't be importable and `import viz.*` below would fail.  Put it there
# first (idempotent when launched another way).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from viz.config import (
    LEVEL_INDEX,
    MAP_HEIGHT,
    MAP_LEVELS,
    MAP_STYLES,
    STANDBY_MAP_HEIGHT,
    default_timescope,
)
from viz.data import (
    CORE_VIS_TABLES,
    fetch_active_units,
    fetch_areas,
    fetch_header_metrics,
    get_viz_engine,
    missing_core_tables,
)
from viz.header import format_area_km2, format_mw, format_unit_count, scope_title
from viz.map_builder import build_deck, build_source_layers
from viz.palette import SOURCE_LAYER_ORDER, source_color
from viz.tooltip import DECK_TOOLTIP, source_header, unit_tooltip

# Sources in sidebar display order: generators top, storage last (bio → storage),
# mirroring the canonical palette ordering reversed from SOURCE_LAYER_ORDER.
SOURCE_DISPLAY_ORDER: tuple[str, ...] = tuple(reversed(SOURCE_LAYER_ORDER))

# Colored bullet before each per-source checkbox label.  Label text is
# sanitized markdown (no inline HTML), so the dots arrive as CSS keyed on the
# widget's `st-key-<key>` class, painted with the source's palette color.
SOURCE_BULLET_STYLES = "\n".join(
    (
        f"[data-testid='stSidebar'] .st-key-source_{source} "
        "[data-testid='stWidgetLabel'] p::before "
        f"{{ content: '● '; color: {source_color(source)}; }}"
    )
    for source in SOURCE_DISPLAY_ORDER
)

st.set_page_config(page_title="German Energy Units", layout="wide")

# Trim the main-area margins so the map window dominates the page instead of
# floating in a large padded block; hide the Streamlit status bar / main menu
# so it doesn't overlap the header; size the compact header strip (labels and
# values on one line); then paint the per-source sidebar bullets.
st.markdown(
    "<style>"
    ".block-container { padding-top: 0.5rem; padding-bottom: 0.5rem; }"
    "#MainMenu, header { visibility: hidden; }"
    ".hdr-row { display: flex; flex-wrap: wrap; gap: 0.3rem 2.5rem; "
    "align-items: baseline; margin: 0.25rem 0 0.25rem; }"
    ".hdr-label { color: #5f6368; font-size: 0.8rem; margin-right: 0.4rem; }"
    ".hdr-value { font-size: 1.05rem; font-weight: 600; }"
    f"{SOURCE_BULLET_STYLES}"
    "</style>",
    unsafe_allow_html=True,
)

# An unreachable database fails the engine connect; both cases mean the same
# thing to the user, so both land on the standby map.  Anything else (a
# misconfigured DATABASE_URL, a real bug) must fail loudly, not masquerade as
# missing tables.
try:
    engine = get_viz_engine()
    missing = missing_core_tables(engine)
except SQLAlchemyError:
    missing = list(CORE_VIS_TABLES)

if missing:
    missing_names = ", ".join(f"`core.{table}`" for table in missing)
    with st.container(height=100):
        st.warning(
            f"No core tables in the database — {missing_names} are missing. "
            "Load them with `python -m etl run-all`."
        )
    st.pydeck_chart(build_deck(), width="stretch", height=STANDBY_MAP_HEIGHT)
    st.stop()

# ── Sidebar: source checkboxes + check-all ────────────────────────────── #

st.sidebar.header("Energy sources")


def _toggle_all_sources():
    """Sync every per-source checkbox when the check-all toggle changes."""
    target = st.session_state["sources_all"]
    for source in SOURCE_DISPLAY_ORDER:
        st.session_state[f"source_{source}"] = target


select_all = st.sidebar.checkbox(
    "Select all sources",
    value=True,
    key="sources_all",
    on_change=_toggle_all_sources,
)
checked_sources: list[str] = [
    source
    for source in SOURCE_DISPLAY_ORDER
    if st.sidebar.checkbox(
        source.title(),
        value=select_all,
        key=f"source_{source}",
    )
]

# ── Sidebar: scope ─────────────────────────────────────────────────────── #

st.sidebar.header("Scope")
level_label = st.sidebar.selectbox(
    "Scope",
    MAP_LEVELS,
    key="level",
    label_visibility="collapsed",
)

# ── Sidebar: timescope ─────────────────────────────────────────────────── #

st.sidebar.header("Timescope")
active_from, active_to = st.sidebar.date_input(
    "Active from / to",
    value=default_timescope(),
    key="timescope",
)

# ── Map style ──────────────────────────────────────────────────────────── #

map_style_label = st.sidebar.selectbox("Map style", list(MAP_STYLES))

# ── Fetch + render ─────────────────────────────────────────────────────── #

units = fetch_active_units(
    engine,
    active_from=active_from,
    active_to=active_to,
    sources=tuple(checked_sources),
)
for rows in units.values():
    for row in rows:
        row["source_header"] = source_header(row)
        row["unit_body"] = unit_tooltip(row)

# ── Header aggregates (issue #25) ──────────────────────────────────────── #

# The level drives the displayed-area scope; the metrics share the map's
# exact timescope predicate and checked-source set, so all four header values
# track every filter change on the same rows the layers render.  The strip
# renders label + value on one line each (CSS `.hdr-row`), smaller than
# st.metric's stacked layout.
areas = fetch_areas(engine, LEVEL_INDEX[level_label])
metrics = fetch_header_metrics(
    engine,
    active_from=active_from,
    active_to=active_to,
    sources=tuple(checked_sources),
)

header_cells = "".join(
    f"<span class='hdr-label'>{html.escape(str(label))}</span>"
    f"<span class='hdr-value'>{html.escape(str(value))}</span>"
    for label, value in (
        ("Scope", scope_title(level_label, areas["area_count"], areas.get("area_name"))),
        ("Installed capacity (MW)", format_mw(metrics["capacity_mw"])),
        ("Active units", format_unit_count(metrics["unit_count"])),
        ("Area (km²)", format_area_km2(areas["total_area_km2"])),
    )
)
st.markdown(f"<div class='hdr-row'>{header_cells}</div>", unsafe_allow_html=True)

layers = build_source_layers(units)
st.pydeck_chart(
    build_deck(
        layers=layers,
        map_style=MAP_STYLES[map_style_label],
        tooltip=DECK_TOOLTIP,
    ),
    width="stretch",
    height=MAP_HEIGHT,
)