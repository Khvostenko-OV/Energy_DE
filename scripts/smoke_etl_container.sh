#!/usr/bin/env bash
# Smoke test for the containerized ETL stack (issue #13 acceptance criteria).
#
# Proves, on a genuinely fresh stack: the pipeline image builds, compose brings
# up a PostGIS database and the pipeline, the containerized `run_all` completes
# every stage (failing loudly on any drift), and the three marts are produced
# at region grain including the `outside` bucket.
#
# This is the seam the containerization work is verified against; issue #16
# (full-stack verification incl. Metabase) builds on it. The pipeline's own
# integration suite still owns pipeline semantics.
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

FAILURES=0

step() { printf '\n=== %s ===\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1" >&2; FAILURES=$((FAILURES + 1)); }

query() {
    docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -tAc "$1"
}

# Assert `psql` returns an integer count and that `count OP expected`.
expect_count() {
    local desc="$1" op="$2" expected="$3" sql="$4"
    local actual
    actual="$(query "$sql")" || { fail "$desc (query failed)"; return; }
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

step "Building the pipeline image"
docker compose build pipeline

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

if [ "$FAILURES" -gt 0 ]; then
    printf '\nSMOKE FAILED: %d assertion(s) failed.\n' "$FAILURES" >&2
    exit 1
fi

printf '\nSMOKE PASSED: containerized run_all completed and the three marts\n'
printf 'are populated at region grain, including the outside bucket.\n'