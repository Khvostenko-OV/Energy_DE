"""Streamlit + PyDeck visualization layer (issue #23).

A self-contained Streamlit app rendering the Germany overview on a CARTO Light
basemap, with a read-only database layer and a separate runtime
(`requirements-viz.txt`).  The `etl` package is imported read-side (schema
constants) but never imports `viz`, keeping the two runtimes apart.
"""
