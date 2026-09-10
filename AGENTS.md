# AGENTS.md

## Project status
Greenfield — **no application code, git repo, or build config exists yet.** The entire ETL pipeline
(GeoPandas → PostGIS → Metabase) still needs to be written. Treat `TechnicalSpecification.md` as the
single authoritative source for data models, table schemas (raw/staging/core/marts), and pipeline design.

## Planned stack (from spec)
- Python (Pandas, GeoPandas) for ETL
- PostgreSQL + PostGIS (PostGIS required for spatial joins)
- Metabase for dashboard/visualization
- Docker + GitHub Actions for infra/CI (not yet set up; Docker and psql are available on this machine)

## Location of your data
| What | Where |
|------|-------|
| Raw unit GPKG files (8 sources incl. Solar polygons, cogeneration) | `data/geo/*.gpkg` |
| Germany boundaries (state, regions+EEZ, districts, municipalities) | `data/geo/germany_*.gpkg` |
| Source documentation | `data/geo/data_descriptor_V20260203.xlsx` |

Gotchas:
- **Actual filenames/versions differ from `TechnicalSpecification.md`**: files are `V20260203`
  (spec says `V20250101`) and the gas file is `Gas_Producer_V20260203.gpkg` (spec says
  `Gas_Production`). Trust the files, not the spec.
- `.venv` exists but is empty (only pip). You must create `requirements.txt` and install
  pandas/geopandas etc. before any code can run.

## Conventions to follow
- Where the spec and files conflict, the files/source datasets win — note the discrepancy rather than silently assuming.
- Follow the spec's ETL stages exactly (extract → staging → core → marts), including normalized
  `parameters` / `units_parameters` dimension tables and materialized views.

## Verification
No tests, linters, or formatters exist yet. A sensible first milestone: get the Extract stage
reading a `.gpkg` into a GeoDataFrame inside the venv and print the schema of `data_descriptor` columns.

## Agent skills

### Issue tracker

Issues live as GitHub issues, managed via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` at the repo root, ADRs in `docs/adr/`. See `docs/agents/domain.md`.