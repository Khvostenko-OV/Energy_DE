# Duplicate municipality names in `service.boundaries` are a documented collision, fix deferred

The seeded `service.boundaries` municipality layer (level 3) carries 27 duplicated names — 428 rows for 401 unique names — each pair being two distinct, non-identical polygons that share a name: one gemeinde/Stadt-sized and one Kreis/Kreisfreie-Stadt-sized (e.g. "Cuxhaven": 0.1 km² and 2,059 km²; "Dithmarschen": 15 km² and 1,428 km²; "Landkreis Rostock": 0.1 km² and 3,429 km²), all `country_iso='DEU'` and `ST_Equals` false. The collision is recorded here, not fixed: the remedy (drop the county-sized polygon at load, de-duplicate name-based joins in the ETL/viz, or key boundaries by more than `name`) is still under consideration. Levels 0–2 have no duplicates, so only the Municipalities grain is affected.

## Consequences

- `name` is the join key the transform spatial join and the viz area filter / choropleth use; at level 3 the two rows answer to the same name, so a name-based filter matches both and both render and count as one area.
- The viz Municipalities multiselect lists 428 options (27 names twice); the area-count / km² header figures and choropleth fills at that grain include the county-scale polygon under the duplicate name.
- A fix must decide which polygon is canonical per duplicated name (layered-hierarchy, area-size, or source-file provenance) before touching the load or the joins.