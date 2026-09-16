#!/bin/sh
# Pipeline container entrypoint.
#
# The CLI reads DATABASE_URL from its environment (etl/config.py); on a seeded
# stack those connection settings live in the detached data volume
# (/app/data/docker.env), not baked into the image or compose config. Source
# them unless the operator already supplied a DATABASE_URL, then hand off to
# the command unchanged. No pipeline code changes are made.
set -e

if [ -z "${DATABASE_URL:-}" ] && [ -n "${DATA_ENV_FILE:-}" ] && [ -f "$DATA_ENV_FILE" ]; then
    # shellcheck disable=SC1090
    . "$DATA_ENV_FILE"
fi

exec "$@"