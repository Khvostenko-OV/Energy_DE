"""Streamlit entrypoint for the German Energy Units map (issue #23).

T1 tracer: renders the Germany overview on the CARTO Light (Positron) basemap.
When the core tables are absent — or the database is unreachable — the app
hides the data widgets and shows only a full-width "No core tables" notice
plus the empty basemap deck.  Widget defaults come from `viz.config`, the
deck from `viz.map_builder`, and the standby check from `viz.data`.
"""

from __future__ import annotations

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from viz.config import MAP_STYLES
from viz.data import CORE_VIS_TABLES, missing_core_tables
from viz.map_builder import build_deck

st.set_page_config(page_title="German Energy Units", layout="wide")
st.title("German Energy Units")

# An unreachable database fails the engine connect; both cases mean the same
# thing to the user, so both land on the standby map.  Anything else (a
# misconfigured DATABASE_URL, a real bug) must fail loudly, not masquerade as
# missing tables.
try:
    missing = missing_core_tables()
except SQLAlchemyError:
    missing = list(CORE_VIS_TABLES)

if missing:
    missing_names = ", ".join(f"`core.{table}`" for table in missing)
    st.warning(
        f"No core tables in the database — {missing_names} are missing. "
        "Load them with `python -m etl run-all`."
    )
    st.pydeck_chart(build_deck())
    st.stop()

map_style = st.sidebar.selectbox("Map style", list(MAP_STYLES))
st.pydeck_chart(build_deck(map_style=MAP_STYLES[map_style]))
