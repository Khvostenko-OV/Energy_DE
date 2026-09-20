#!/usr/bin/env bash
# Smoke test for the containerized ETL + viz stack (issue #13/#28 acceptance).
#
# Proves, on a genuinely fresh stack: the pipeline and viz images build, compose
# brings up a PostGIS database, the pipeline, and the viz app, the containerized
# `run_all` completes every stage (failing loudly on any drift), the three
# marts are produced at region grain including the `outside` bucket, the
# read-only `viz_reader` role is provisioned and can read core/service/marts,
# and the viz service passes Streamlit's `/_stcore/health` probe on port 8501.
#
# This is the seam the containerization work is verified against; issue #16
# (full-stack verification) builds on it. The pipeline's own integration suite
# still owns pipeline semantics.
#
# Usage:  scripts/smoke_etl_container.sh
#
# Requires docker (with the aarch64/arm64 platforms as needed) and the private
# raw data set under data/ (used only to seed the volume).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VOLUME_NAME="${ETL_DATA_VOLUME:-etl_data}"
DB_USER="${DB_USER:-etl}"
DB_NAME="${DB_NAME:-energy_de}"
VIZ_PORT="${VIZ_PORT:-8501}"
VIZ_USER="${VIZ_USER:-viz_reader}"
VIZ_PASSWORD="${VIZ_PASSWORD:-viz}"

FAILURES=0

step() { printf '\n=== %s ===\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1" >&2; FAILURES=$((FAILURES + 1)); }

query() {
    docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -tAc "$1"
}

# The same credentials the seeded VIZ_DATABASE_URL carries: TCP (scram, needs
# the password) as the read-only role, not the local socket (trust). This is
# the app's exact connect path, so a pass here proves the pair end to end.
query_viz() {
    docker compose exec -T -e PGPASSWORD="$VIZ_PASSWORD" db psql \
        -h 127.0.0.1 -U "$VIZ_USER" -d "$DB_NAME" -tAc "$1"
}

# Assert `psql` returns an integer count and that `count OP expected`.
# `runner` defaults to `query`; a check that must run as the read-only role
# (its own DB account / connection path) passes `query_viz`.
expect_count() {
    local desc="$1" op="$2" expected="$3" sql="$4" runner="${5:-query}"
    local actual
    actual="$($runner "$sql")" || { fail "$desc (query failed)"; return; }
    case "$actual" in
        '' | *[!0-9-]*)
            fail "$desc (not an integer count: '$actual')"
            return
            ;;
    esac
    if [ "$((actual))" "$op" "$((expected))" ]; then
        printf 'PASS: %s (%s %s %s)\n' "$desc" "$actual" "$op" "$expected"
    else
        printf 'FAIL: %s (got %s, expected %s %s)\n' "$desc" "$actual" "$op" "$expected" >&2
        FAILURES=$((FAILURES + 1))
    fi
}

step "Building the pipeline and viz images"
docker compose build pipeline viz

step "Fresh start: teardown existing stack and volumes (db + seeded data)"
docker compose down -v --remove-orphans >/dev/null
# The data volume is external to compose, so `down -v` alone does not drop it;
# remove it explicitly for a genuinely fresh seed.
docker volume rm -f "$VOLUME_NAME" >/dev/null 2>&1 || true

step "Seeding the detached data volume (one-time per machine, idempotent)"
"$REPO_ROOT/scripts/seed_data_volume.sh" "$VOLUME_NAME"

step "Bringing up PostGIS and waiting for it to be healthy"
docker compose up -d --wait db

step "Running the containerized pipeline (python -m etl run-all)"
# `run` attaches to the already-up db service and returns the container's exit
# code, so a failing stage (or mart drift) fails the smoke run loudly.
docker compose run --rm -T pipeline

step "Verifying the three marts at region grain (incl. outside bucket)"
expect_count "materialized mart views exist" -eq 3 \
    "SELECT count(*) FROM pg_matviews WHERE schemaname='marts' AND matviewname IN ('installation_counts','generation_capacity','storage_capacity')"

expect_count "installation_counts has rows" -gt 0 \
    "SELECT count(*) FROM marts.installation_counts"
expect_count "generation_capacity has rows" -gt 0 \
    "SELECT count(*) FROM marts.generation_capacity"
expect_count "storage_capacity has rows" -gt 0 \
    "SELECT count(*) FROM marts.storage_capacity"

expect_count "installation_counts region grain has no NULL regions" -eq 0 \
    "SELECT count(*) FROM marts.installation_counts WHERE region IS NULL"
expect_count "generation_capacity region grain has no NULL regions" -eq 0 \
    "SELECT count(*) FROM marts.generation_capacity WHERE region IS NULL"
expect_count "storage_capacity region grain has no NULL regions" -eq 0 \
    "SELECT count(*) FROM marts.storage_capacity WHERE region IS NULL"

expect_count "'outside' bucket appears across the marts" -gt 0 \
    "SELECT count(*) FROM (
        SELECT 'installation_counts' AS mart FROM marts.installation_counts WHERE region='outside'
        UNION ALL
        SELECT 'generation_capacity' AS mart FROM marts.generation_capacity WHERE region='outside'
        UNION ALL
        SELECT 'storage_capacity' AS mart FROM marts.storage_capacity WHERE region='outside'
    ) o"

step "Mart sample rows"
docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT * FROM marts.installation_counts ORDER BY region LIMIT 8"
docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT * FROM marts.storage_capacity ORDER BY region LIMIT 5"

step "Provisioning: viz_reader role (idempotent SQL seam)"
# The role was created from /docker-entrypoint-initdb.d when the fresh db
# volume initialized; re-running the same file proves the seam is idempotent.
if docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" \
    -f /docker-entrypoint-initdb.d/99-viz-reader.sql >/dev/null 2>&1; then
    printf 'PASS: viz_reader provisioning re-run (idempotent)\n'
else
    fail "viz_reader provisioning re-run"
fi
expect_count "viz_reader role exists" -eq 1 \
    "SELECT count(*) FROM pg_roles WHERE rolname='viz_reader'"

step "viz_reader can read core/service/marts over the app's TCP path"
expect_count "viz_reader reads core.generators" -gt 0 \
    "SELECT count(*) FROM core.generators" query_viz
expect_count "viz_reader reads core.storages" -gt 0 \
    "SELECT count(*) FROM core.storages" query_viz
expect_count "viz_reader reads service.boundaries" -gt 0 \
    "SELECT count(*) FROM service.boundaries" query_viz
expect_count "viz_reader reads the marts materialized views" -gt 0 \
    "SELECT count(*) FROM marts.installation_counts" query_viz

step "metabase service dropped from the compose stack"
if docker compose config --services | grep -qx metabase; then
    fail "metabase still present in compose"
else
    printf 'PASS: compose has no metabase service\n'
fi

step "Bringing up the viz service (Streamlit, port ${VIZ_PORT})"
docker compose up -d --wait viz

step "Viz health probe (Streamlit /_stcore/health)"
if curl -fsS "http://127.0.0.1:${VIZ_PORT}/_stcore/health" | grep -qx ok; then
    printf 'PASS: /_stcore/health returned ok (port %s)\n' "$VIZ_PORT"
else
    fail "viz health probe on port $VIZ_PORT"
fi

step "Viz app shell reachable (no auth)"
if curl -fsS -o /dev/null "http://127.0.0.1:${VIZ_PORT}/"; then
    printf 'PASS: viz app served at http://localhost:%s\n' "$VIZ_PORT"
else
    fail "viz app not served at http://localhost:$VIZ_PORT"
fi

step "Seeded volume carries VIZ_DATABASE_URL the app reads"
if docker compose exec -T viz grep -q "^export VIZ_DATABASE_URL=postgresql://$VIZ_USER:" \
    /app/data/docker.env; then
    printf 'PASS: VIZ_DATABASE_URL present in docker.env (viz container mount)\n'
else
    fail "VIZ_DATABASE_URL missing from /app/data/docker.env"
fi

if [ "$FAILURES" -gt 0 ]; then
    printf '\nSMOKE FAILED: %d assertion(s) failed.\n' "$FAILURES" >&2
    exit 1
fi

printf '\nSMOKE PASSED: containerized run_all completed, the three marts\n'
printf 'are populated at region grain (incl. the outside bucket), the\n'
printf 'read-only viz_reader role reads core/service/marts, and the viz\n'
printf 'service answers its health probe on port %s.\n' "$VIZ_PORT"