# Renewable Energy Installations in Germany

Geospatial registry of renewable energy installations in Germany, with an ETL pipeline
(GeoPandas → PostGIS marts) for analyzing installed capacity by energy source, state,
and commissioning date, and a Streamlit + PyDeck map app that visualises the marts.

## Status

Implemented. The ETL pipeline (extract → staging → core → marts) runs end-to-end via the CLI
(`python -m etl <stage>`, or `run-all` for the whole pass; Click hyphenates the `run_all`
Python function name) and is covered by a full integration
test suite (pytest, 120+ tests against a PostGIS dev DB), and the Streamlit viz app
(`viz/`, T1–T4, no-auth map with per-source scatter layers, area choropleth and header
aggregates) runs in the containerized stack. Design work recorded in:

- **Spec** — `TechnicalSpecification.md` (authoritative source of truth for data models and stages)
- **Domain glossary** — `CONTEXT.md`
- **Architecture decisions** — `docs/adr/`
- **Tickets** — GitHub issues in this repo, labelled `ready-for-agent`, with blocking edges wired
  (`#2` onwards; the spec lives in `#1`)

## Stack

- Python (Pandas, GeoPandas)
- PostgreSQL + PostGIS (`energy_de` database)
- Streamlit + PyDeck (`viz/` — the deployed visualization app, reads the marts through a
  read-only `viz_reader` role)
- Docker (containerized stack — `compose.yaml`: db + pipeline + viz images, data-volume
  seed, read-only role provisioning; `docs/containerization.md`)
- GitHub Actions (CI smoke gates — `.github/workflows/ci.yml`: byte-compile + pipeline image build, #14)

## Data

| What                                                                 | Where                                     |
|----------------------------------------------------------------------|-------------------------------------------|
| Raw unit GPKG files (6 sources incl. solar, wind, storage)           | `data/sources/*.gpkg`                     |
| Germany boundaries (states + EEZ, regions, districts)                | `data/boundaries/germany_*.gpkg`          |
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
`installed_capacity` (ADR 0002), marts as materialized views at state grain (ADR 0003), versioned
raw datalake (ADR 0004), quality annotations as property links (ADR 0005), per-kind property tables
(ADR 0006), operational metadata in the `service` schema (ADR 0007).

See `CONTEXT.md` for the glossary and `docs/adr/` for the rationale behind these choices.

## Configuration

`extract` and `boundaries` take their target from two env vars with repo-root
defaults, so they run with **no arguments** — an explicit `TARGET` always wins:

| Env var | Default | Meaning |
|---------|---------|---------|
| `SOURCES_DATA_DIR` | `<repo>/data/sources` | folder scanned for `*_V<YYYYMMDD>.gpkg` unit-source files (the six sources in `SOURCE_NAMES` order; `Solar_Energy_Polygons` / `Cogeneration_Units` look-alikes are logged and skipped) |
| `BOUNDARIES_MANIFEST` | `<repo>/data/boundaries/boundaries.txt` | manifest listing the `germany_*.gpkg` boundary files, each file's `level` read from its data |

Both are documented (commented) in `.env.example`. `run-all` uses the same
configured paths, so a bare `python -m etl run-all` needs no arguments at all.

## Deploy

Two supported ways to run the stack; the containerized one is the deploy path.

### Containerized stack (recommended)

Requires Docker, the private raw data set under `data/` (sources + boundaries), and
a running PostGIS database*.

```sh
cp .env.example .env          # optional; overrides documented defaults
scripts/seed_data_volume.sh   # one-time: copies data/ + docker.env into the etl_data volume
docker compose -f local_compose.yaml up --build --wait db viz
```

- `db` provisions the schemas and the read-only `viz_reader` role on a fresh volume
  (`docker/viz_reader.sql`); `pipeline` runs `run-all` on demand
  (`docker compose -f local_compose.yaml run --rm pipeline`); `viz` serves the
  Streamlit app on http://localhost:8501. (The server/deploy variant is
  `compose.yaml` — nginx entry point, no published viz port.)
- Verify the marts:
  `docker compose -f local_compose.yaml exec -T db psql -U etl -d energy_de -c "SELECT * FROM marts.installation_counts ORDER BY state LIMIT 8"`
- *Alternative: seed a remote PostGIS and point the seed script's `DB_HOST`/`DB_PORT`
  env at it — see `docs/remote-deploy.md`.

### Dev host (CI-style)

```sh
.venv/bin/pip install -r requirements.txt -r requirements-viz.txt   # requirements-viz.txt is self-contained (viz-only)
cp .env.example .env          # set DATABASE_URL (and VIZ_DATABASE_URL) to your PostGIS
python -m etl run-all         # extract → staging → core → marts
.venv/bin/streamlit run viz/app.py
```

### Reset / clean slate

```sh
scripts/drop_pipeline_data.sh # empties raw/stage/core/marts/service (schemas kept)
python -m etl run-all         # rebuild from the raw data
```

> **Upgrading a database seeded before the states/regions/districts rename (#32):**
> there is no migration code — drop the pipeline data and re-run
> (`scripts/drop_pipeline_data.sh && python -m etl run-all`); staging/core are
> dropped and recreated on every load and the marts views are rebuilt.

Full walkthrough, configuration table, and teardown: `docs/containerization.md`.
