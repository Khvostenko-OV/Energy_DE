"""Streamlit + PyDeck visualization layer (issue #23).

A self-contained Streamlit app rendering the Germany overview on a CARTO Light
basemap, with a read-only database layer and a separate runtime
(`requirements-viz.txt`).  Fully standalone: it never imports `etl` — its
`.env`-driven settings (schema names, connection URLs) live in `viz/config.py`,
defaults pinned to the etl originals by `tests/test_viz_config.py`.
"""
