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
those areas (units whose state/region/district names one of them); on
the all-areas selection every active unit renders and counts, including
offshore units that belong to no polygon at the active level.  At the country
level ("Germany") the area multiselect is omitted and the choropleth gives
way to a plain country-boundary outline — there is nothing to compare by
color within a single polygon.

The T4 fetch path is the render-optimized one (docs/Viz_optimazation.md):
units come back in **one pandas frame via at most two queries** (generators
once with `energy_source = ANY(:sources)`, storages once), the per-area
choropleth fill is a pandas groupby over that frame's `name` column — no
spatial join — and the boundary layer outlines **every** area at the level
while filling only the selected ones.  The header's scope/capacity/unit-count
figures derive from the same frame and boundary rows, so a rerun issues the
two unit queries plus one boundaries query.

T1 tracer (#23): when the core tables are absent — or the database is
unreachable — the app hides the data widgets and shows only a full-width
"No core tables" notice plus the empty basemap deck.  Widget defaults come
from `viz.config`, the deck from `viz.map_builder`, the fetch from `viz.data`,
the tooltip from `viz.tooltip`, and the header strings from `viz.header`.
The choropleth and camera seams live in `viz.choropleth` / `viz.viewport`.
"""

from __future__ import annotations

import html
import json
import sys
import time
from pathlib import Path
from typing import Any

# Streamlit adds only this script's folder to sys.path, so the repo root
# wouldn't be importable and `import viz.*` below would fail.  Put it there
# first (idempotent when launched another way).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from viz.choropleth import area_fills, areas_feature_collection
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
    fetch_area_names,
    fetch_boundaries,
    fetch_units,
    get_viz_engine,
    missing_core_tables,
    unit_records,
)
from viz.header import (
    areas_summary,
    format_area_km2,
    format_mw,
    format_unit_count,
    scope_title,
)
from viz.map_builder import (
    build_boundary_layer,
    build_choropleth_layer,
    build_deck,
    build_source_layers,
)
from viz.palette import SOURCE_LAYER_ORDER, source_color
from viz.tooltip import DECK_TOOLTIP, attach_tooltips
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

# ── Boundary data cache (issue #31) ──────────────────────────────────────── #
# `st.pydeck_chart` re-runs this script on every widget interaction.  The
# boundary payload depends only on the level, so it is cached server-side
# keyed on ``(level, str(engine.url))`` — the SQLAlchemy ``Engine`` object is
# never hashed, and the ``engine_url`` argument exists purely as that key; the
# bodies read the module-global ``engine`` resolved above (fresh per script
# run, so a changed `VIZ_DATABASE_URL` yields a fresh key and a cache miss).
# On a cache hit the wrapped functions return without touching the database,
# so a rerun over an unchanged level issues no boundaries query and skips the
# per-row ``json.loads`` (parsed geometries ride along with the rows in one
# cache entry).  `viz/data.py` stays pure: its ``fetch_*`` signatures are
# untouched.
def _cache_boundary_payload(
    engine_url: str, level: int
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Boundary rows and their parsed geometries for a level, cached per engine url."""
    rows = fetch_boundaries(engine, level=level)
    geometries = {row["name"]: json.loads(row["geojson"]) for row in rows}
    return rows, geometries


def _cache_area_names(engine_url: str, level: int) -> list[str]:
    """Area names of a level (multiselect options), cached per engine url."""
    return fetch_area_names(engine, level)


_cached_boundary_payload = st.cache_data(show_spinner=False)(_cache_boundary_payload)
_cached_area_names = st.cache_data(show_spinner=False)(_cache_area_names)

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
level_lab = st.sidebar.selectbox(
    "Level",
    MAP_LEVELS,
    key="level",
    label_visibility="collapsed",
)
level_label = level_lab.split(' ')[0]
level = LEVEL_INDEX[level_label]

# The multiselect options are the area names at the active level, fetched
# live.  It starts empty on purpose — every level switch lands on a fresh
# widget with nothing picked, so the user chooses what to display — and, per
# the spec, an empty selection means "all areas" too.  The widget key embeds
# the level, so switching levels starts from a fresh no-selection pick
# instead of leaking the previous level's names into the new one.  At the
# country level ("Germany", a single polygon) there is no area choice to
# make, so the widget is omitted and the scope is always the whole country.
area_names = _cached_area_names(str(engine.url), level)
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
# proper subset of the level's areas: a unit's state/region/district
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
    label_visibility="collapsed",
)

# ── Map style ──────────────────────────────────────────────────────────── #

map_style_label = st.sidebar.selectbox("Map style", list(MAP_STYLES))

# Manual invalidation of the boundary data cache after a pipeline re-run; the
# click itself reruns the script, and the next fetch misses the cache.
st.sidebar.button(
    "Reload data",
    on_click=st.cache_data.clear,
    help="Re-fetch the cached boundary data after loading new data with the pipeline.",
)

# ── Fetch + render ─────────────────────────────────────────────────────── #

print("Rendering", len(area_filter_names or []), level_label)
_timing_start = time.perf_counter()
_checkpoint_start = _timing_start

# ── Units: one DataFrame, ≤2 queries (render-opt) ───────────────────────── #
# Every checked source resolves in at most two queries (core.generators once
# for all generator sources, core.storages once for storage) and the frame
# carries the active level's area attribute as `name`, so the same rows feed
# the scatter layers, the per-area choropleth fill and the header totals.
units = fetch_units(
    engine,
    active_from=active_from,
    active_to=active_to,
    sources=tuple(checked_sources),
    area_column=area_column,
    area_names=area_filter_names or (),
)
print(f"[timing] fetch_units: {time.perf_counter() - _checkpoint_start:.2f}s")
_checkpoint_start = time.perf_counter()

units = attach_tooltips(units)
print(f"[timing] tooltips: {time.perf_counter() - _checkpoint_start:.2f}s")
_checkpoint_start = time.perf_counter()

# ── Choropleth fill + boundaries (render-opt, issue #31) ───────────────────── #
# The fill is a pandas groupby over the units frame's `name` column — no
# spatial join — and the boundaries fetch covers every area at the level so
# the layer outlines the whole level and fills only the displayed selection.
# The boundary rows + parsed geometries come from the server-side cache, so a
# rerun over an unchanged level issues no boundaries DB query and skips the
# per-row json.loads.  At the country level the fill is skipped (no `name`
# column) since the boundary layer paints no choropleth there.
fills = area_fills(units)
boundary_rows, boundary_geometries = _cached_boundary_payload(
    str(engine.url), level
)
features = areas_feature_collection(
    boundary_rows,
    fills,
    selected_names=selected_names,
    pre_parsed_geometry=boundary_geometries,
)
print(f"[timing] area_fills + fetch_boundaries + features: {time.perf_counter() - _checkpoint_start:.2f}s")
_checkpoint_start = time.perf_counter()

# ── Camera (issue #26) ──────────────────────────────────────────────────── #

# The camera is fitted to the selected areas' bounding box and stored in
# session state.  It is replaced only when the level or area selection changes
# (or on the first run); every source/timescope rerun over the same scope keeps
# the stored camera, so the deck's unchanged initial view lets the frontend
# preserve the user's own framing.  Points come from the displayed selection
# only — the context outlines beyond it must not move the camera.
selected_set = frozenset(selected_names)
camera_points = [
    point
    for feature in features["features"]
    if feature["properties"]["name"] in selected_set
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

# ── Header aggregates (issue #25, render-opt) ───────────────────────────── #
# The scope figures come from the boundary rows already fetched for the
# choropleth (count, km² sum, single name over the selection) and the capacity
# / unit-count from the units frame itself — no extra queries.  On the
# all-areas selection the figures are simply the level-wide totals.
areas = areas_summary(boundary_rows, selected_names)
metrics = {
    "capacity_mw": float(units["installed_capacity"].sum()) / 1000.0,
    "unit_count": len(units),
}

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
print(f"[timing] header: {time.perf_counter() - _checkpoint_start:.2f}s")
_checkpoint_start = time.perf_counter()

# Area fills paint below the unit points, so points stay legible on top of the
# choropleth; the camera comes from the session state above.  At the country
# level the choropleth gives way to the plain boundary layer (no fill).  Each
# scatter layer reads the JSON-ready records of one energy_source group.
area_layer = (
    build_boundary_layer(features)
    if level_label == "Germany"
    else build_choropleth_layer(features)
)
source_records = {
    source: unit_records(group)
    for source, group in units.groupby("energy_source")
}
layers = [area_layer, *build_source_layers(source_records)]
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
colorbar_max = max((row["capacity_mw"] for row in fills), default=0.0)
if level_label != "Germany" and colorbar_max > 0:
    st.markdown(colorbar_html(colorbar_max), unsafe_allow_html=True)

print(f"[timing] colorbar: {time.perf_counter() - _checkpoint_start:.2f}s")
print(f"[timing] TOTAL: {time.perf_counter() - _timing_start:.2f}s")
print()
