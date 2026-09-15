# AGENTS.md

## Project status
Implemented. The ETL pipeline (GeoPandas → PostGIS) runs end-to-end from the CLI
(`python -m etl <stage>`, incl. `run_all`) and is covered by a full integration test suite.
Treat `TechnicalSpecification.md` as the single authoritative source for data models, table
schemas (raw/staging/service/core/marts), and pipeline design.

## Stack (from spec)
- Python (Pandas, GeoPandas) for ETL — in use
- PostgreSQL + PostGIS (PostGIS required for spatial joins) — in use
- Metabase for dashboard/visualization — planned (marts are Metabase-ready)
- Docker + GitHub Actions for infra/CI — planned (Docker and psql are available on this machine)

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
(`DATABASE_URL` via `.env`) and the raw data files. Docker + CI are planned (tickets #13–#16);
the raw data and the suite stay private either way.

## Agent skills

### Issue tracker

Issues live as GitHub issues, managed via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` at the repo root, ADRs in `docs/adr/`. See `docs/agents/domain.md`.