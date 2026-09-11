# Renewable Energy Installations in Germany

Geospatial registry of renewable energy installations in Germany, with an ETL pipeline
(GeoPandas → PostGIS → Metabase-ready marts) for analyzing installed capacity by energy
source, region, and commissioning date.

## Status

Greenfield. The pipeline is not implemented yet. Design work is done:

- **Spec** — `TechnicalSpecification.md` (authoritative source of truth for data models and stages)
- **Domain glossary** — `CONTEXT.md`
- **Architecture decisions** — `docs/adr/`
- **Tickets** — GitHub issues in this repo, labelled `ready-for-agent`, with blocking edges wired
  (`#2` onwards; the spec lives in `#1`)

## Stack

- Python (Pandas, GeoPandas)
- PostgreSQL + PostGIS (`energy_de` database)
- Metabase (planned, out of current scope)

## Data

| What                                                                 | Where                                     |
|----------------------------------------------------------------------|-------------------------------------------|
| Raw unit GPKG files (6 sources incl. solar, wind, storage)           | `data/geo/*.gpkg`                         |
| Germany boundaries (state, regions + EEZ, districts, municipalities) | `data/geo/germany_*.gpkg`                 |
| Source documentation                                                 | `data/geo/data_descriptor_V20260203.xlsx` |

All files are 2026-02-03 versions. The files are authoritative.

## Pipeline

Four PostGIS stages, run per-stage or as one pass via the planned CLI (`python -m etl <stage>`):

1. **Extract** — read unit sources into versioned `raw.<source>_<date>_<n>` tables guarded by the `loaded_files` log and `-f` force flag; boundaries into `raw.boundaries`; secondary attributes folded into a `secondary_attributes` jsonb column
2. **Transform** — natural staging identity, spatial joins against boundaries, quality gating (`bad_quality` + property links), attributes decomposed to `properties` / `units_properties`
3. **Load** — consolidated `generators` and `storages` in `core` (serial keys, geometry-matched in-place updates, `collision` flags annotated as property links)
4. **Marts** — three Postgres materialized views (installation counts, generation capacity, storage capacity) over active units

Each stage verifies its own output (row counts, key uniqueness, join coverage, idempotency) and
fails loudly on violation. Key decisions: staging identity from `reference_id`, core serial keys with
geometry-matched updates gated on `reference_date` (ADR 0001), gas production capacity recorded as
`installed_capacity` (ADR 0002), marts as materialized views at region grain (ADR 0003), versioned
raw datalake (ADR 0004), quality annotations as property links (ADR 0005).

See `CONTEXT.md` for the glossary and `docs/adr/` for the rationale behind these choices.
