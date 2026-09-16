"""Dash entrypoint for the unit-layer scatter map (issue #18).

Serves a single-page app on port 8050: a `dcc.Graph` whose figure is built by
`viz.figure.build_units_map` from the PostGIS-backed query functions in
`viz.data`.  The figure is produced on page load (the browser request drives
the callback), never at import time — so importing this module needs no
database, which keeps gunicorn workers and the container healthcheck (issue
#21) cheap.
"""

from __future__ import annotations

from dash import Dash, Input, Output, dcc, html

from viz.data import fetch_generators, fetch_storages, get_viz_engine
from viz.figure import build_units_map

app = Dash(__name__)
app.title = "German Energy Units"
server = app.server

app.layout = html.Div(
    [
        dcc.Graph(id="units-map", config={"displayModeBar": False}),
        # Data-less store drives the initial page-load callback.
        dcc.Store(id="units-store", data={}),
    ],
    style={"height": "100vh"},
)


@app.callback(Output("units-map", "figure"), Input("units-store", "data"))
def render_units_map(_):
    engine = get_viz_engine()
    generators = fetch_generators(engine)
    storages = fetch_storages(engine)
    return build_units_map(generators, storages)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=False)