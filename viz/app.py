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
    fetch_generators,
    fetch_level_fills,
    fetch_storages,
    get_viz_engine,
    load_level_geojson,
)
from viz.drill import CAPACITY_MW, UNIT_COUNT, plan_drill
from viz.figure import add_choropleth_fill, build_units_map, centroids_by_name

INITIAL_STATE = {
    "level": 1,
    "parent_filters": {},
    "metric": CAPACITY_MW,
    "centre": None,
}

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
        dcc.RadioItems(
            id="metric-toggle",
            options=[
                {"label": "Installed capacity (MW)", "value": CAPACITY_MW},
                {"label": "Unit count", "value": UNIT_COUNT},
            ],
            value=CAPACITY_MW,
            style={"position": "absolute", "top": 10, "left": 10, "zIndex": 9},
        ),
        # Drill state: active boundary level + the accumulated parent-name
        # chain that scopes that level's live aggregate.
        dcc.Store(id="drill-state", data=INITIAL_STATE),
        # Data-less store drives the initial page-load callback.
        dcc.Store(id="units-store", data={}),
    ],
    style={"height": "100vh", "margin": 0},
)


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
    target = plan_drill(state.get("level", 1), clicked_area, metric, chain)

    if target is None:
        return dict(INITIAL_STATE, metric=metric)

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
    generators = fetch_generators(engine)
    storages = fetch_storages(engine)
    fills = fetch_level_fills(level, parent_filters, metric, engine)

    fig = build_units_map(generators, storages)
    add_choropleth_fill(fig, load_level_geojson(level), fills, metric)
    data = fig.to_dict()
    if state.get("centre"):
        lon, lat = state["centre"]
        data["layout"]["map"]["center"] = {"lat": lat, "lon": lon}
    return data


@app.callback(
    Output("units-map", "figure"),
    Input("units-store", "data"),
    Input("metric-toggle", "value"),
    Input("drill-state", "data"),
)
def render_units_map(_, metric, drill_state):
    state = dict(drill_state or INITIAL_STATE)
    state["metric"] = metric
    return _build_map(state)


@app.callback(
    Output("drill-state", "data"),
    Input("units-map", "clickData"),
    State("drill-state", "data"),
    State("metric-toggle", "value"),
)
def drill_on_click(click_data, drill_state, metric):
    clicked_area = (
        click_data["points"][0].get("location")
        if click_data and click_data.get("points")
        else None
    )
    state = dict(drill_state or INITIAL_STATE)
    state["metric"] = metric
    return next_drill_state(state, clicked_area)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=False)