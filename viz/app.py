"""Streamlit entrypoint for the German Energy Units map (issues #23-#26).

T2 (#24): renders one scatter layer per checked energy source with
active-units timescope filtering, a sidebar check-all toggle, per-source
checkboxes, a date-range timescope, and a hover card for every unit.

T3 (#25): a live header above the map.  The header shows the active drill
level and the count of displayed areas — or the single area's name when
exactly one area is shown (e.g. "Region Berlin") — plus total installed
capacity (MW), the active-unit count, and the displayed area in km².  All
figures recompute on every rerun (source/timescope/level changes) and pull
from the same predicate the map renders.

T4 (#26): the administrative-level slice.  An area multiselect below the
level selectbox picks the displayed areas at the active level (starts empty;
empty selection means all areas), a choropleth GeoJsonLayer colors each area
by its live capacity (per-area unit count on hover), computed from the same
source/timescope filters as the scatter and header, and the camera refits to
the selected areas' bounding box only when the level or area selection
changes — session-state camera survives every other rerun.  With a proper
subset of areas picked, the scatter points and every header figure narrow to
those areas (units whose region/district/municipality names one of them); on
the all-areas selection every active unit renders and counts, including
offshore units that belong to no polygon at the active level.  At the country
level ("Germany") the area multiselect is omitted and the choropleth gives
way to a plain country-boundary outline — there is nothing to compare by
color within a single polygon.

T1 tracer (#23): when the core tables are absent — or the database is
unreachable — the app hides the data widgets and shows only a full-width
"No core tables" notice plus the empty basemap deck.  Widget defaults come
from `viz.config`, the deck from `viz.map_builder`, the fetch from `viz.data`,
the tooltip from `viz.tooltip`, and the header strings from `viz.header`.
The choropleth and camera seams live in `viz.choropleth` / `viz.viewport`.
"""

from __future__ import annotations

import html
import sys
import time
from pathlib import Path

# Streamlit adds only this script's folder to sys.path, so the repo root
# wouldn't be importable and `import viz.*` below would fail.  Put it there
# first (idempotent when launched another way).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from viz.choropleth import areas_feature_collection
from viz.config import (
    LEVEL_INDEX,
    LEVEL_UNIT_AREA_COLUMN,
    MAP_HEIGHT,
    MAP_LEVELS,
    MAP_STYLES,
    STANDBY_MAP_HEIGHT,
    default_timescope,
)
from viz.colorbar import colorbar_html
from viz.data import (
    CORE_VIS_TABLES,
    fetch_active_units,
    fetch_area_names,
    fetch_areas,
    fetch_boundaries,
    fetch_boundary_fill,
    fetch_header_metrics,
    get_viz_engine,
    missing_core_tables,
)
from viz.header import format_area_km2, format_mw, format_unit_count, scope_title
from viz.map_builder import (
    build_boundary_layer,
    build_choropleth_layer,
    build_deck,
    build_source_layers,
)
from viz.palette import SOURCE_LAYER_ORDER, source_color
from viz.tooltip import DECK_TOOLTIP, source_header, unit_tooltip
from viz.viewport import fit_viewstate, geometry_points, should_refit

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
    ".block-container { padding: 0.25rem 2rem 0.5rem 2rem; }"
    "#MainMenu, header { visibility: hidden; }"
    ".hdr-row { display: flex; flex-wrap: wrap; gap: 0.3rem 0.3rem; "
    "align-items: baseline; margin: 0 0 0.25rem; }"
    ".hdr-label { color: #5f6368; font-size: 0.9rem; margin-right: 0.2rem; }"
    ".hdr-value { font-size: 1.2rem; font-weight: 600; margin-right: 1.5rem; }"
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
    with st.container(height=80):
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
    "Level",
    MAP_LEVELS,
    key="level",
    label_visibility="collapsed",
)
level = LEVEL_INDEX[level_label]

# The multiselect options are the area names at the active level, fetched
# live.  It starts empty on purpose — every level switch lands on a fresh
# widget with nothing picked, so the user chooses what to display — and, per
# the spec, an empty selection means "all areas" too.  The widget key embeds
# the level, so switching levels starts from a fresh no-selection pick
# instead of leaking the previous level's names into the new one.  At the
# country level ("Germany", a single polygon) there is no area choice to
# make, so the widget is omitted and the scope is always the whole country.
area_names = fetch_area_names(engine, level)
if level_label == "Germany":
    selected_names: tuple[str, ...] = tuple(area_names)
else:
    selected_areas = st.sidebar.multiselect(
        "Areas",
        options=area_names,
        key=f"areas_{level_label}",
    )
    selected_names = tuple(selected_areas or area_names)

# The scatter points and header metrics follow the selection only when it is a
# proper subset of the level's areas: a unit's region/district/municipality
# attribute must name one of the picked areas.  On the all-areas selection no
# filter applies, so units that belong to no polygon at the active level still
# render and count.
area_column = LEVEL_UNIT_AREA_COLUMN[level_label]
area_filter_names: tuple[str, ...] | None = (
    selected_names
    if area_column is not None and len(selected_names) < len(area_names)
    else None
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

print("Rendering", level_label)
_timing_start = time.perf_counter()
_checkpoint_start = _timing_start

units = fetch_active_units(
    engine,
    active_from=active_from,
    active_to=active_to,
    sources=tuple(checked_sources),
    area_column=area_column,
    area_names=area_filter_names or (),
)
print(f"[timing] fetch_active_units: {time.perf_counter() - _checkpoint_start:.2f}s")
_checkpoint_start = time.perf_counter()
for rows in units.values():
    for row in rows:
        row["source_header"] = source_header(row)
        row["unit_body"] = unit_tooltip(row)
print(f"[timing] tooltips: {time.perf_counter() - _checkpoint_start:.2f}s")
_checkpoint_start = time.perf_counter()

# ── Choropleth fetch (issue #26) ───────────────────────────────────────── #

# The area fill shares the scatter/header predicate and checked-source set, so
# the choropleth colors exactly the units the points and header totals count;
# the boundaries (name + GeoJSON) are fetched over the same displayed scope,
# and the two are joined by area name.  With nothing checked the fill query is
# skipped (zero fill everywhere) while the boundaries still render; at the
# country level the fill is skipped too, since the boundary layer paints no
# choropleth there.
boundary_rows = fetch_boundaries(engine, level=level, names=selected_names)
print(f"[timing] fetch_boundaries: {time.perf_counter() - _checkpoint_start:.2f}s")
_checkpoint_start = time.perf_counter()
if level_label == "Germany":
    fill_rows = []
else:
    fill_rows = fetch_boundary_fill(
        engine,
        level=level,
        names=selected_names,
        active_from=active_from,
        active_to=active_to,
        sources=tuple(checked_sources),
    )
print(f"[timing] fetch_boundary_fill: {time.perf_counter() - _checkpoint_start:.2f}s")
_checkpoint_start = time.perf_counter()
features = areas_feature_collection(boundary_rows, fill_rows)
print(f"[timing] areas_feature_collection: {time.perf_counter() - _checkpoint_start:.2f}s")
_checkpoint_start = time.perf_counter()

# ── Camera (issue #26) ──────────────────────────────────────────────────── #

# The camera is fitted to the selected areas' bounding box and stored in
# session state.  It is replaced only when the level or area selection changes
# (or on the first run); every source/timescope rerun over the same scope keeps
# the stored camera, so the deck's unchanged initial view lets the frontend
# preserve the user's own framing.
camera_points = [
    point
    for feature in features["features"]
    for point in geometry_points(feature["geometry"])
]
if should_refit(
    st.session_state.get("camera"),
    st.session_state.get("camera_scope"),
    level_label=level_label,
    area_names=selected_names,
):
    st.session_state["camera"] = fit_viewstate(camera_points)
    st.session_state["camera_scope"] = (
        level_label,
        tuple(sorted(selected_names)),
    )
camera = st.session_state["camera"]
print(f"[timing] camera fit: {time.perf_counter() - _checkpoint_start:.2f}s")
_checkpoint_start = time.perf_counter()

# ── Header aggregates (issue #25) ──────────────────────────────────────── #

# Every header figure follows the selection like the scatter: the scope/area
# cells narrow to the picked areas and the metrics to the units whose
# region/district/municipality names one of them, so a chosen area reads as
# "Region Berlin" with Berlin's capacity, units and km².  On the all-areas
# selection the figures are simply the level-wide totals.  The metrics share
# the map's exact timescope predicate and checked-source set, so all four
# header values track every filter change on the same rows the layers render.
# The strip renders label + value on one line each (CSS `.hdr-row`), smaller
# than st.metric's stacked layout.
areas = fetch_areas(engine, level, names=selected_names)
metrics = fetch_header_metrics(
    engine,
    active_from=active_from,
    active_to=active_to,
    sources=tuple(checked_sources),
    area_column=area_column,
    area_names=area_filter_names or (),
)

header_cells = "".join(
    f"<span class='hdr-label'>{html.escape(str(label))}</span>"
    f"<span class='hdr-value'>{html.escape(str(value))}</span>"
    for label, value in (
        ("", scope_title(level_label, areas["area_count"], areas.get("area_name"))),
        ("Installed capacity (MW)", format_mw(metrics["capacity_mw"])),
        ("Active units", format_unit_count(metrics["unit_count"])),
        ("Area (km²)", format_area_km2(areas["total_area_km2"])),
    )
)
st.markdown(f"<div class='hdr-row'>{header_cells}</div>", unsafe_allow_html=True)
print(f"[timing] fetch_areas + fetch_header_metrics + header: {time.perf_counter() - _checkpoint_start:.2f}s")
_checkpoint_start = time.perf_counter()

# Area fills paint below the unit points, so points stay legible on top of the
# choropleth; the camera comes from the session state above.  At the country
# level the choropleth gives way to the plain boundary layer (no fill).
area_layer = (
    build_boundary_layer(features)
    if level_label == "Germany"
    else build_choropleth_layer(features)
)
layers = [area_layer, *build_source_layers(units)]
print(f"[timing] build layers: {time.perf_counter() - _checkpoint_start:.2f}s")
_checkpoint_start = time.perf_counter()
st.pydeck_chart(
    build_deck(
        layers=layers,
        map_style=MAP_STYLES[map_style_label],
        lon=camera["lon"],
        lat=camera["lat"],
        zoom=camera["zoom"],
        tooltip=DECK_TOOLTIP,
    ),
    width="stretch",
    height=MAP_HEIGHT,
)
print(f"[timing] pydeck_chart: {time.perf_counter() - _checkpoint_start:.2f}s")
_checkpoint_start = time.perf_counter()

# The colorbar floats over the map's right edge whenever the choropleth paints
# a real capacity ramp (Germany has no choropleth, and an all-zero or empty
# fill has nothing to scale) — the top label is the largest area fill across
# the displayed scope, matching the ramp's high end.
colorbar_max = max((row["capacity_mw"] for row in fill_rows), default=0.0)
if level_label != "Germany" and colorbar_max > 0:
    st.markdown(colorbar_html(colorbar_max), unsafe_allow_html=True)

print(f"[timing] colorbar: {time.perf_counter() - _checkpoint_start:.2f}s")
print(f"[timing] TOTAL: {time.perf_counter() - _timing_start:.2f}s")
print()
