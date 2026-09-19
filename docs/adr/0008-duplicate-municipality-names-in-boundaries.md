# Duplicate municipality names in `service.boundaries` are a documented collision, fix deferred

The seeded `service.boundaries` municipality layer (level 3) carries 27 duplicated names — 428 rows for 401 unique names — each pair being two distinct, non-identical polygons that share a name: one gemeinde/Stadt-sized and one Kreis/Kreisfreie-Stadt-sized (e.g. "Cuxhaven": 0.1 km² and 2,059 km²; "Dithmarschen": 15 km² and 1,428 km²; "Landkreis Rostock": 0.1 km² and 3,429 km²), all `country_iso='DEU'` and `ST_Equals` false. The collision is recorded here, not fixed: the remedy (drop the county-sized polygon at load, de-duplicate name-based joins in the ETL/viz, or key boundaries by more than `name`) is still under consideration. Levels 0–2 have no duplicates, so only the Municipalities grain is affected.

## Consequences

- `name` is the join key the transform spatial join and the viz area filter / choropleth use; at level 3 the two rows answer to the same name, so a name-based filter matches both and both render and count as one area.
- The viz Municipalities multiselect lists 428 options (27 names twice); the area-count / km² header figures and choropleth fills at that grain include the county-scale polygon under the duplicate name.
- A fix must decide which polygon is canonical per duplicated name (layered-hierarchy, area-size, or source-file provenance) before touching the load or the joins.

## Summary (2026-09-19)

Issue \#29 was resolved by replacing the prior `germany_munis.gpkg` (which was actually Landkreis‑level, 428 rows / 401 unique names) with two new reference layers derived from the canonical BKG VG250 source:

- `germany_municipalities.gpkg` — 10,956 true municipalities (Gemeinden), columns `name/iso/ags/geometry`, CRS EPSG:4326. Polygon‑part duplicates were collapsed via `union_all()` per AGS; the 22 city/county name pairs (e.g. `Ansbach Stadt` / `Ansbach Landkreis`) remain as distinct AGS‑keyed rows.
- `germany_kreise.gpkg` — 400 Landkreise/kreisfreie Städte, columns `name/iso/ags/geometry`, CRS EPSG:4326. Same dedup logic; kreisfreie Stadt names receive the `"Stadt"` suffix.

The new files (`germany_municipalities.gpkg`, `germany_kreise.gpkg`) together with the build scripts (`scripts/build_gemeinde.py`, `scripts/build_kreise.py`) provide a durable data‑source remedy, obviating the need for a load‑time dedup gate or a consumer‑layer key change. The ADR \#8 collision is now recorded as resolved; any future VG250 freeze can be re‑processed with the same scripts.

## Consequences

- `name` is the join key the transform spatial join and the viz area filter / choropleth use; at level 3 the two rows answer to the same name, so a name-based filter matches both and both render and count as one area (this behaviour persists for the 22 city/county name pairs that share a name but have different AGS — intentionally, as they are distinct administrative units).
- The viz Municipalities multiselect now lists 10,956 options (the true municipality count); area‑count / km² header figures and choropleth fills at the municipality grain reflect the correct single‑row-per‑municipality data.
- The Kreis layer (`germany_kreise.gpkg`) replaces the prior `germany_munis.gpkg` concept and is the authoritative source for district‑level boundaries.
- ADR \#8 is updated from “fix deferred” to “resolved via VG250 data‑source swap”.