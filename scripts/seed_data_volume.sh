#!/usr/bin/env bash
# One-time manual seed (per machine) for the containerized ETL stack (issue #13).
#
# Copies the private raw data set (data/sources + data/boundaries, including the
# manifest files) and the connection settings into a detached Docker named
# volume. The pipeline container mounts that volume at /app/data and reads the
# connection settings from docker.env before running the CLI.
#
# The raw files stay out of git (data/sources, data/boundaries are ignored); the
# seed is the only step that ever touches them.
#
# Usage:  scripts/seed_data_volume.sh [VOLUME_NAME]
#         VOLUME_NAME defaults to ${ETL_DATA_VOLUME:-etl_data} (must match
#         compose.yaml's volume).
#
# Re-runnable: re-running overwrites the volume contents.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_ROOT="${DATA_ROOT:-$REPO_ROOT/data}"
VOLUME_NAME="${ETL_DATA_VOLUME:-${1:-etl_data}}"

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-etl}"
DB_PASSWORD="${DB_PASSWORD:-etl}"
DB_NAME="${DB_NAME:-energy_de}"

if [ ! -d "$DATA_ROOT/sources" ] || [ ! -d "$DATA_ROOT/boundaries" ]; then
    echo "error: raw data set not found under $DATA_ROOT" >&2
    echo "       (need $DATA_ROOT/sources and $DATA_ROOT/boundaries)" >&2
    exit 1
fi

docker volume create "$VOLUME_NAME" >/dev/null

HELPER="etl-data-seed-helper"
docker rm -f "$HELPER" >/dev/null 2>&1 || true
docker run --rm -d --name "$HELPER" -v "${VOLUME_NAME}:/data" alpine:3.20 sleep 3600 >/dev/null
trap 'docker rm -f "$HELPER" >/dev/null 2>&1 || true' EXIT

echo "Seeding volume '$VOLUME_NAME' from $DATA_ROOT"
docker cp "$DATA_ROOT/sources/." "$HELPER":/data/sources
docker cp "$DATA_ROOT/boundaries/." "$HELPER":/data/boundaries

docker exec -i "$HELPER" sh -c "cat > /data/docker.env" <<EOF
export DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}
EOF

echo
echo "Volume contents:"
docker exec "$HELPER" sh -c "find /data -type f | sort"
echo
echo "Connection settings written to $VOLUME_NAME:/data/docker.env:"
echo "  DATABASE_URL=postgresql://$DB_USER:*****@$DB_HOST:$DB_PORT/$DB_NAME"
echo
echo "Seeded. A fresh machine is now self-contained — run the pipeline with:"
echo "  docker compose up --build"