#!/usr/bin/env bash
# Empty the pipeline schemas on a local database (clean-slate reset).
#
# Runs scripts/drop_all_pipeline_data.sql — drops every table, view,
# materialized view, and standalone sequence in raw/stage/core/marts/service,
# leaving the schemas (and their ACLs, incl. the viz_reader grants) in place.
# Afterwards, `python -m etl run-all` rebuilds everything from the raw data.
#
# Target resolution order:
#   1. $DATABASE_URL from the environment
#   2. DATABASE_URL from the repo-root .env (the dev-host convention the ETL
#      and viz app use via python-dotenv)
#   3. a URL built from the composable DB_* vars (compose defaults, like the
#      seed script)
#
# Destructive by design: the script re-prompts for confirmation against the
# database name parsed from the resolved URL, unless you pass -f/--force.
#
# Usage:  scripts/drop_pipeline_data.sh [-f]
#         -f | --force   skip the confirmation prompt
#
# For the containerized db, either set DATABASE_URL to its published port, or
# run the SQL directly inside the db container:
#   docker compose exec -T db psql -U etl -d energy_de \
#     -f /app/scripts/drop_all_pipeline_data.sql

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SQL_FILE="$REPO_ROOT/scripts/drop_all_pipeline_data.sql"
[ -f "$SQL_FILE" ] || { echo "error: $SQL_FILE not found" >&2; exit 1; }

FORCE=0
case "${1:-}" in
    -f | --force) FORCE=1 ;;
    "") ;;
    *) echo "usage: $0 [-f|--force]" >&2; exit 2 ;;
esac

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-etl}"
DB_PASSWORD="${DB_PASSWORD:-etl}"
DB_NAME="${DB_NAME:-energy_de}"

if [ -z "${DATABASE_URL:-}" ] && [ -f "$REPO_ROOT/.env" ]; then
    # Mirror the dotenv convention: .env only contributes when the operator
    # hasn't already exported the URL.
    set -a
    # shellcheck disable=SC1091
    . "$REPO_ROOT/.env"
    set +a
    echo "Using DATABASE_URL from $REPO_ROOT/.env"
fi
DATABASE_URL="${DATABASE_URL:-postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME}"

TARGET_DB="$(printf '%s\n' "$DATABASE_URL" | sed -E 's#.*/([^/?]*)(\?.*)?$#\1#')"
MASKED="$(printf '%s\n' "$DATABASE_URL" | sed -E 's#(://[^:@]+):[^@]+@#\1:*****@#')"

command -v psql >/dev/null || { echo "error: psql not found in PATH" >&2; exit 1; }

echo "Drops ALL tables/views/matviews/sequences in: raw, stage, core, marts, service"
echo "Target: $MASKED (database '$TARGET_DB')"
if [ "$FORCE" -eq 0 ]; then
    printf 'Type the database name (%s) to confirm, anything else to abort: ' "$TARGET_DB"
    read -r REPLY
    [ "$REPLY" = "$TARGET_DB" ] || { echo "aborted."; exit 1; }
fi

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$SQL_FILE"

echo
echo "Schemas emptied. Rebuild them from the raw data with:"
echo "  python -m etl run-all"