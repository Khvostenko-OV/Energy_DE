# Code review — containerized ETL (#13)

- **Date:** 2026-09-16
- **Fixed point:** `HEAD` (41b3982) — review of the uncommitted working tree (the work was committed after review)
- **Diff:** `git diff HEAD` + new untracked files (`.dockerignore`, `Dockerfile`, `compose.yaml`, `docker/entrypoint.sh`, `scripts/seed_data_volume.sh`, `scripts/smoke_etl_container.sh`, `docs/containerization.md`)
- **Spec source:** GitHub issue #13 (fetched via `gh issue view 13`)
- **Reviewed artifacts:** pipeline container image build, compose stack (PostGIS `db` + `pipeline`), one-time data-volume seed procedure, containerized `run-all` + mart verification smoke, containerization docs (and AGENTS.md/README.md doc reconciliation)

## Standards

Two parallel-review findings:

1. **Hard — stale README Stack row.** The changeset split "Docker + GitHub Actions" in AGENTS.md (Docker #13 in use, GHA #14 planned) but left README.md:25 as `Docker + GitHub Actions (infra/CI, planned)`. A single logical change (Docker ships) landed in only one of the two living docs. **Fixed:** README Stack row now mirrors AGENTS.md.

2. Judgeable smells, accepted deliberately:
   - **Primitive Obsession** — the `etl`/`etl` default credentials appear in three places (compose, seed script, docs). Accepted for a local-dev stack and documented as a coupled pair; the seed echoes them masked.
   - **Minor indirection** — `query()` helper in the smoke script used by one caller. Left as-is; it names the sql-against-db seam.

Verified correct: `set -euo pipefail` on host scripts (entrypoint uses `set -e` under BusyBox `/bin/sh`), idempotent seed/re-runs, `.dockerignore` excludes data/secret/tooling, no duplicated logic between seed and smoke (the smoke calls the seed), docs internally consistent.

## Spec

All four acceptance criteria satisfied; no pipeline code changed (`git diff etl/` empty):

| AC | Result |
|----|--------|
| Pipeline image builds and exposes the same `python -m etl` stages | ✅ `Dockerfile` + `CMD python -m etl`; `docker compose run --rm pipeline python -m etl --help` lists extract, boundaries, transform, load, marts, run-all |
| Compose provisions PostGIS + pipeline; containerized `run-all` completes every stage, verifies marts, fails loudly on drift | ✅ `compose.yaml` `depends_on` health-gated; marts stage exits non-zero on drift and `docker compose run` propagates the container exit code |
| Documented one-time manual seed (detached data volume + connection settings, once per machine) | ✅ `scripts/seed_data_volume.sh` + `docs/containerization.md` |
| Freshly seeded run produces the three marts at region grain incl. `outside` | ✅ `scripts/smoke_etl_container.sh` asserts all three views exist, non-empty, no NULL regions, `outside` bucket present — passed end-to-end |

### Findings raised during verification

1. **`run_all` vs `run-all`.** Click 8.5 exposes the `run_all` Python function as the CLI command `run-all` (underscores → hyphens) — on the host too. The image and compose use `run-all`; docs/AGENTS/README record the naming. Pipeline code unchanged.
2. **`down -v` does not remove an `external` volume.** The spec review flagged the first cut of the teardown doc claimed `down -v` deletes `etl_data`; Docker Compose never removes external volumes. **Fixed:** docs now state the external volume detaches and how to truly reset it (`docker volume rm` + re-seed); the smoke explicitly removes the data volume before re-seeding.
3. **PostGIS init/restart healthcheck race (smoke-found, not reviewer-found).** The postgres image runs a temporary socket-only init server to apply the PostGIS extension scripts, then restarts; a socket-checking `pg_isready` goes green during init, so the pipeline started into the restart window and hit `Connection refused`. **Fixed:** healthcheck forces TCP (`-h 127.0.0.1`), staying unhealthy until the real listener accepts. Smoke passed end-to-end with the fix.

## Summary

Standards: 2 findings (1 hard, fixed; 1 accepted judgement call). Worst: stale README Stack row. Spec: 0 open findings; 3 verification findings, all fixed and re-verified by the smoke seam. Overall the containerized stack meets all #13 acceptance criteria with no pipeline code changes.