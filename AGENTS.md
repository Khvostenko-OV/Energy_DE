# AGENTS.md

## Project status
Implemented. The ETL pipeline (GeoPandas → PostGIS) runs end-to-end from the CLI
(`python -m etl <stage>`, incl. `run-all`; Click hyphenates the `run_all` Python
function name) and is covered by a full integration test suite. Containerized:
a pipeline image + PostGIS + Streamlit-viz compose stack with a one-time data-volume
seed, read-only `viz_reader` role provisioning (dev-host SQL seam in
`docker/viz_reader.sql`), and a smoke seam (`compose.yaml`,
`scripts/seed_data_volume.sh`, `scripts/smoke_etl_container.sh`; see
`docs/containerization.md`).
Treat `TechnicalSpecification.md` as the single authoritative source for data models, table
schemas (raw/staging/service/core/marts), and pipeline design.

## Stack (from spec)
- Python (Pandas, GeoPandas) for ETL — in use
- PostgreSQL + PostGIS (PostGIS required for spatial joins) — in use
- Docker for the containerized stack — in use (compose: db + pipeline + viz, #13/#15/#28)
- Streamlit + PyDeck for the visualization app — in use (the `viz/` package, issues #23+,
  shipped as its own compose `viz` service behind the read-only `viz_reader` role, #28;
  the aborted Dash/Metabase approaches were dropped with the `dash-viz-service` branch
  and #28)

## Location of your data
| What | Where |
|------|-------|
| Raw unit GPKG files (6 sources loaded; Solar polygons & Cogeneration on disk but not loaded) | `data/sources/*.gpkg` |
| Germany boundaries (state, regions+EEZ, districts, municipalities) | `data/boundaries/germany_*.gpkg` |
| Source documentation | `data/sources/data_descriptor_V20260203.xlsx` |

Gotchas:
- **Actual filenames/versions differ from `TechnicalSpecification.md`**: files are `V20260203`
  (spec says `V20250101`) and the gas file is `Gas_Producer_V20260203.gpkg` (spec says
  `Gas_Production`). Trust the files, not the spec.
- The `.venv` is populated; install with `.venv/bin/pip install -r requirements.txt -r requirements-dev.txt`.
  The viz layer (`viz/`, Streamlit + PyDeck) additionally needs `-r requirements-viz.txt`.
- `DATABASE_URL` and the raw data are required to run the pipeline; both stay out of git.

## Conventions to follow
- Where the spec and files conflict, the files/source datasets win — note the discrepancy rather than silently assuming.
- Follow the spec's ETL stages exactly (extract → staging → core → marts), including
  per-unit-kind property tables (`generator_properties` dimension +
  `generator_units_properties` links, `storage_properties` + `storage_units_properties`
  dimension and links — ADR 0006) and the materialized-view marts.
- Operational metadata (load log + boundary reference layer) lives in the `service` schema
  (ADR 0007), not in raw.

## Verification
pytest is the only test runner (`.venv/bin/python -m pytest`); there are no linters or
typecheckers. The full integration suite is the verification bar — it needs a PostGIS dev DB
(`DATABASE_URL` via `.env`) and the raw data files. The viz unit seams
(`tests/test_viz_*.py`) take no database but do need `requirements-viz.txt` installed.
The containerized stack has its own smoke
seam (`scripts/smoke_etl_container.sh`, #13; extended by #28 for db + pipeline + viz);
CI is planned (#14). The raw data and the suite
stay private either way.

## Agent skills

### Issue tracker

Issues live as GitHub issues, managed via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` at the repo root, ADRs in `docs/adr/`. See `docs/agents/domain.md`.