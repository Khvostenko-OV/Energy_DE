"""Dash entrypoint for the unit-layer scatter map with choropleth drill (issues #18/#19).

Serves a single-page app on port 8050: a `dcc.Graph` whose figure is built by
`viz.figure.build_units_map` plus the active drill level's choropleth fill
(`viz.figure.add_choropleth_fill`) from the PostGIS-backed query functions in
`viz.data`.  A click on the map's choropleth fill drills one boundary level
down (region → district → municipality), scoped by the accumulated parent-name
chain; a level-3 click re-centers instead of drilling.  A radio toggle swaps
the fill metric between the installed-capacity MW sum (default) and the unit
count.  The figure is produced on page load (the browser request drives the
callback), never at import time — so importing this module needs no database,
which keeps gunicorn workers and the container healthcheck (issue #21) cheap.
"""

from __future__ import annotations

import dash
from dash import Dash, Input, Output, State, dcc, html

from viz.data import (
    CoreTablesMissing,
    fetch_generators,
    fetch_level_fills,
    fetch_storages,
    get_viz_engine,
    load_level_geojson,
    missing_core_tables,
)
from viz.drill import CAPACITY_MW, UNIT_COUNT, plan_drill
from viz.figure import (
    DRILL_ZOOMS,
    GERMANY_CENTER,
    add_choropleth_fill,
    build_units_map,
    centroids_by_name,
)

INITIAL_STATE = {
    "level": 1,
    "parent_filters": {},
    "metric": CAPACITY_MW,
    "centre": None,
}

# Explicit camera for the whole-country overview.  INITIAL_STATE keeps
# centre=None so the very first render uses the figure's default (GERMANY_CENTER),
# but any reset — button, empty-map click, level-3 click — must re-frame the
# map on Germany explicitly, otherwise plotly leaves the camera parked on the
# last drilled region.
OVERVIEW_CENTRE = (GERMANY_CENTER["lon"], GERMANY_CENTER["lat"])


def overview_state(metric=CAPACITY_MW) -> dict:
    """The country-overview drill state, recentred on Germany."""
    return dict(INITIAL_STATE, metric=metric, centre=OVERVIEW_CENTRE)

app = Dash(__name__)
app.title = "German Energy Units"
server = app.server

app.layout = html.Div(
    [
        dcc.Graph(
            id="units-map",
            config={"displayModeBar": False},
            style={"height": "100vh"},
        ),
        # Standby message over the map when the core tables are absent (the
        # pipeline has not loaded them yet, or a test run dropped them).
        html.Div(
            id="core-status",
            children=[],
            style={
                "position": "absolute",
                "top": "50%",
                "left": "50%",
                "transform": "translate(-50%, -50%)",
                "zIndex": 10,
                "pointerEvents": "none",
                "color": "#666",
                "fontSize": 18,
                "textAlign": "center",
                "maxWidth": "60%",
            },
        ),
        dcc.RadioItems(
            id="metric-toggle",
            options=[
                {"label": "Installed capacity (MW)", "value": CAPACITY_MW},
                {"label": "Unit count", "value": UNIT_COUNT},
            ],
            value=CAPACITY_MW,
            style={"position": "absolute", "top": 10, "left": 10, "zIndex": 9},
        ),
        # Escape hatch from a drilled level back to the country overview.  The
        # button only shows once the drill is past level 1; clicking it resets
        # the drill state (keeping the metric toggle).
        html.Button(
            "Reset to Germany",
            id="reset-button",
            style={
                "position": "absolute",
                "top": 10,
                "right": 10,
                "zIndex": 9,
                "display": "none",
            },
        ),
        # Drill state: active boundary level + the accumulated parent-name
        # chain that scopes that level's live aggregate.
        dcc.Store(id="drill-state", data=INITIAL_STATE),
        # Data-less store drives the initial page-load callback.
        dcc.Store(id="units-store", data={}),
    ],
    style={"height": "100vh", "margin": 0},
)


def state_after_click(drill_state, clicked_area, was_map_click):
    """Resolve the next drill state from a real map click (pure, testable).

    ``was_map_click`` distinguishes an actual click on the map from the
    click-less page-load callback: only real clicks act.  A click with no
    area name — the sea, or an empty region with no fill — escapes back to
    the country overview, so a drilled Berlin/Hamburg/EEZ can always be
    left; an area click delegates to `next_drill_state`.
    """
    state = dict(drill_state or INITIAL_STATE)
    metric = state.get("metric", CAPACITY_MW)
    if was_map_click and clicked_area is None:
        return overview_state(metric)
    return next_drill_state(state, clicked_area)


def next_drill_state(drill_state, clicked_area):
    """Resolve the next drill state from a choropleth click (pure, testable).

    Returns the state the app should move to: drilling one boundary level down
    scoped by the accumulated parent-name chain (re-centring the map on the
    clicked area's children), or the country-overview initial state when the
    click cannot drill (level 3 — re-center, no drill past it).
    """
    state = dict(drill_state or INITIAL_STATE)
    metric = state.get("metric", CAPACITY_MW)

    if not clicked_area:
        return dict(state, centre=state.get("centre"))

    chain = tuple(state.get("parent_filters", {}).items())
    target = plan_drill(state.get("level", 1), clicked_area, chain)

    if target is None:
        return overview_state(metric)

    centre = centroids_by_name(load_level_geojson(state.get("level", 1))).get(
        clicked_area
    )
    return {
        "level": target.target_level,
        "parent_filters": dict(target.parent_filters),
        "metric": metric,
        "centre": centre,
    }


def _build_map(state: dict) -> dict:
    """Compose the scatter map + choropleth fill for an active drill state."""
    metric = state["metric"]
    level = state["level"]
    parent_filters = state["parent_filters"]

    engine = get_viz_engine()
    missing = missing_core_tables(engine)
    if missing:
        raise CoreTablesMissing(missing)
    generators = fetch_generators(engine, parent_filters)
    storages = fetch_storages(engine, parent_filters)
    fills = fetch_level_fills(level, parent_filters, metric, engine)

    fig = build_units_map(generators, storages)
    add_choropleth_fill(fig, load_level_geojson(level), fills, metric)
    data = fig.to_dict()
    data["layout"]["map"]["zoom"] = DRILL_ZOOMS[level]
    if state.get("centre"):
        lon, lat = state["centre"]
        data["layout"]["map"]["center"] = {"lat": lat, "lon": lon}
    return data


def figure_state(drill_state, metric, trigger):
    """Active state to render for, given who just changed.

    When the reset button triggered the update, return the country overview
    directly — the reset must not rely on the store having been updated first.
    In Dash, two callbacks triggered by the same prop can run in one batch, which
    let the figure rebuild from a stale level-2 store even though the store
    itself moved to level 1 (issue #19 reset regression).
    """
    if trigger == "reset-button":
        return overview_state(metric)
    state = dict(drill_state or INITIAL_STATE)
    state["metric"] = metric
    return state


def core_tables_message(missing) -> list:
    """Standby message shown when the map's core tables are absent."""
    names = ", ".join(f"core.{table}" for table in missing)
    return [
        html.Div(f"The map needs {names}, but they are not in the database yet.",
                 style={"fontWeight": "bold", "marginBottom": 8}),
        html.Div("Load them with:  python -m etl load"),
    ]


@app.callback(
    Output("core-status", "children"),
    Input("drill-state", "data"),
    Input("units-store", "data"),
)
def core_status(drill_state, _units_store):
    """Overlay a standby message when the core tables are absent."""
    try:
        missing = missing_core_tables()
    except Exception:
        return []
    if missing:
        return core_tables_message(missing)
    return []


@app.callback(
    Output("units-map", "figure"),
    Input("units-store", "data"),
    Input("metric-toggle", "value"),
    Input("drill-state", "data"),
    Input("reset-button", "n_clicks"),
)
def render_units_map(_, metric, drill_state, reset_clicks):
    try:
        return _build_map(figure_state(drill_state, metric, dash.callback_context.triggered_id))
    except CoreTablesMissing:
        return dash.no_update


@app.callback(
    Output("drill-state", "data"),
    Input("units-map", "clickData"),
    Input("reset-button", "n_clicks"),
    State("drill-state", "data"),
    State("metric-toggle", "value"),
    prevent_initial_call=True,
)
def resolve_drill_state(click_data, n_clicks, drill_state, metric):
    """Single owner of drill-state: a map click drills, the reset button escapes.

    Both inputs can only change one at a time, so the trigger identifies the
    request — clicking the reset button while drilled never fires the map
    branch.  (Keeping one output owner matters: with two callbacks writing
    drill-state, Dash's last-response-wins silently clobbered drills.)
    """
    state = dict(drill_state or INITIAL_STATE)
    state["metric"] = metric
    if dash.callback_context.triggered_id == "reset-button":
        return overview_state(metric)
    if not click_data:
        # Page-load callback with no click yet; keep the current drill state.
        return state
    points = click_data.get("points") or []
    clicked = points[0] if points else {}
    if clicked.get("location"):
        # A fill-area hit: drill one level into that area.
        return state_after_click(state, clicked["location"], True)
    # No fill area was hit.  A scatter-marker click just keeps state (hover/
    # tooltip); a click on empty map — the sea or a unit-less region — escapes
    # back to the country overview.
    if any("lon" in p or "lat" in p for p in points):
        return state
    return state_after_click(state, None, True)


@app.callback(
    Output("reset-button", "style"),
    Input("drill-state", "data"),
)
def toggle_reset_visibility(drill_state):
    state = dict(drill_state or INITIAL_STATE)
    visible = dict(
        position="absolute",
        top=10,
        right=10,
        zIndex=9,
        display="block",
    )
    if state["level"] == 1:
        visible["display"] = "none"
    return visible


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=False)