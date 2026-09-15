# Renewable Energy Installations in Germany

Geospatial registry of renewable energy installations in Germany, with an ETL pipeline
(GeoPandas → PostGIS → Metabase-ready marts) for analyzing installed capacity by energy
source, region, and commissioning date.

## Status

Implemented. The ETL pipeline (extract → staging → core → marts) runs end-to-end via the CLI
(`python -m etl <stage>`, or `run_all` for the whole pass) and is covered by a full integration
test suite (pytest, 120+ tests against a PostGIS dev DB). Design work recorded in:

- **Spec** — `TechnicalSpecification.md` (authoritative source of truth for data models and stages)
- **Domain glossary** — `CONTEXT.md`
- **Architecture decisions** — `docs/adr/`
- **Tickets** — GitHub issues in this repo, labelled `ready-for-agent`, with blocking edges wired
  (`#2` onwards; the spec lives in `#1`)

## Stack

- Python (Pandas, GeoPandas)
- PostgreSQL + PostGIS (`energy_de` database)
- Metabase (planned — marts are Metabase-ready)
- Docker + GitHub Actions (infra/CI, planned)

## Data

| What                                                                 | Where                                     |
|----------------------------------------------------------------------|-------------------------------------------|
| Raw unit GPKG files (6 sources incl. solar, wind, storage)           | `data/sources/*.gpkg`                     |
| Germany boundaries (state, regions + EEZ, districts, municipalities) | `data/boundaries/germany_*.gpkg`          |
| Source documentation                                                 | `data/sources/data_descriptor_V20260203.xlsx` |

All files are 2026-02-03 versions. The files are authoritative.

## Pipeline

Four PostGIS layers, run per-stage or as one pass via the CLI (`python -m etl <stage>`):

1. **Extract** — read unit sources into versioned `raw.<source>_<date>_<n>` tables guarded by the `service.loaded_files` log and `-f` force flag; reference boundaries into the non-versioned `service.boundaries`; secondary attributes folded into a `secondary_attributes` jsonb column
2. **Transform** — natural staging identity, spatial joins against `service.boundaries`, quality gating (`bad_quality` + property links), attributes decomposed to `properties` / `{source}_units_properties`
3. **Load** — consolidated `generators` and `storages` in `core` (serial keys, record-identity in-place updates, collision flags annotated as property links), per-kind property tables `generator_properties` + `generator_units_properties` and `storage_properties` + `storage_units_properties` (ADR 0006)
4. **Marts** — three Postgres materialized views (installation counts, generation capacity, storage capacity) over active units

Each stage verifies its own output (row counts, key uniqueness, join coverage, idempotency) and
fails loudly on violation. Key decisions: staging identity from `reference_id`, core serial keys with
record-identity updates gated on `reference_date` (ADR 0001), gas production capacity recorded as
`installed_capacity` (ADR 0002), marts as materialized views at region grain (ADR 0003), versioned
raw datalake (ADR 0004), quality annotations as property links (ADR 0005), per-kind property tables
(ADR 0006), operational metadata in the `service` schema (ADR 0007).

See `CONTEXT.md` for the glossary and `docs/adr/` for the rationale behind these choices.
