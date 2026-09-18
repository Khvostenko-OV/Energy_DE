# Visualization of Geodata

## Framework: Streamlit + PyDeck
1. Visualization app deployed in its own container
2. No auth to access
3. Create read-only role in DB to make queries
4. Dev stage locally 

## Layout
1. Header with aggregated info
   - Level and count of selected areas. If one area selected show name - Region Berlin 
   - Total installed capacity (MW) of active units (of selected types and timescope) 
   - Total count of active units
   - Total area (km2) 
2. Sidebar with selectors
   - Checkboxes with energy sources to toggle sources which are shown (incl checkall)
   - Selectbox for level (Germany, Regions, Districts, Municipalities)
   - Selectbox (multi) to choose concreate areas to show (depending on selected level)
   - Selectbox for timescope (from/to) in which units are active
   - Selectbox for map style (Light, Satellite, Topographic)
3. Map window
   - Scatter map layers with energy units, clustered. Each source type colored its own color. 
   Only active units (according to timescope), only checked source types
   - Choropleth layer with areas' boundaries according to level and selected areas
   - Base layer with map according to selected map type
   - Map is centred and zoomed according to selected areas
   - Hovering area show Name, Total capacity, Number of units
   - Hovering unit show Unit info
   - Hovering cluster show Energy source, Total capacity, Number of units
   - Legenda not needed

## UI
- All selected filters are stored in the session state
- If no core tables present in DB show only Base layer map, expose message in Header "No core tables ..."