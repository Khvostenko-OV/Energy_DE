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

1. **Extract** — read unit sources into `raw`, secondary attributes folded into a `properties` dictionary
2. **Transform** — natural-key identity, spatial joins against boundaries, attributes decomposed to `parameters`
3. **Load** — consolidated `generators` and `storages` in `core`, with a `quality_checks` register
4. **Marts** — stored pivot tables (installation counts, generation capacity, storage capacity) + materialized views

Each stage verifies its own output (row counts, key uniqueness, join coverage, idempotency) and
fails loudly on violation. Key decisions: natural key `(energy_source, reference_id)` backed by a
surrogate key in core (ADR 0001), gas production capacity recorded as `installed_capacity`
(ADR 0002), marts as stored wide pivots at region grain (ADR 0003).

See `CONTEXT.md` for the glossary and `docs/adr/` for the rationale behind these choices.