#!/bin/sh
# Shared container entrypoint (pipeline + viz services, issues #13/#28).
#
# The CLI reads DATABASE_URL from its environment (etl/config.py); the viz app
# reads VIZ_DATABASE_URL (viz/data.py). On a seeded stack those connection
# settings live in the detached data volume (/app/data/docker.env), not baked
# into the images or compose config. Source them where neither URL is already
# supplied (an operator-supplied URL always wins), then hand off to the command
# unchanged. No pipeline code changes are made.
set -e

if [ -n "${DATA_ENV_FILE:-}" ] && [ -f "$DATA_ENV_FILE" ] \
    && [ -z "${DATABASE_URL:-}" ] && [ -z "${VIZ_DATABASE_URL:-}" ]; then
    # shellcheck disable=SC1090
    . "$DATA_ENV_FILE"
fi

exec "$@"