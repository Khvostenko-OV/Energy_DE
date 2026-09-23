# Pipeline container image (issue #13; distroless multistage, #34).
#
# Wraps the existing `python -m etl` CLI unchanged — no pipeline code changes.
# The raw data set and connection settings are NOT baked in: they live in the
# detached named volume mounted at /app/data at runtime (seeded once per
# machine, see scripts/seed_data_volume.sh and docs/containerization.md). The
# entrypoint loads /app/data/docker.env so the CLI can build its engine.
#
# Distroless multistage (the Chainguard python-image pattern): the `-dev`
# builder installs the requirements into a venv, and the minimal runtime stage
# copies only the venv + code — no shell, no pip, no build tooling. The runtime
# runs as a non-root user, so `docker compose exec pipeline sh` debugging does
# not exist; the entrypoint is Python, not a shell script.
#
# NOTE (tag): Chainguard's public registry only ships `latest`/`latest-dev`
# (Python 3.14 at the time of writing); the versioned `3.12` tags moved behind
# paid org access. `latest-dev`/`latest` are the free distroless pair.

FROM cgr.dev/chainguard/python:latest-dev AS builder

WORKDIR /app

ENV HOME=/tmp \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# The builder stage runs as root so the venv can live at the spec's /venv;
# only this throwaway stage is root — the runtime image stays non-root and its
# /venv is root-owned but world-readable.
USER root

COPY requirements.txt ./
RUN python -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --only-binary=:all: -r requirements.txt \
    && find /venv -type f -name '*.pyc' -delete \
    && find /venv -type d -name '__pycache__' -empty -delete

FROM cgr.dev/chainguard/python:latest

WORKDIR /app

ENV PATH=/venv/bin:$PATH \
    HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# entrypoint.py carries the +x bit in the build context, so it is executable
# as-is (the distroless runtime has no shell, so no `RUN chmod` is possible).
COPY --from=builder /venv /venv
COPY etl/ ./etl/
COPY docker/entrypoint.py /usr/local/bin/etl-entrypoint

STOPSIGNAL SIGINT

ENTRYPOINT ["/usr/local/bin/etl-entrypoint"]
CMD ["python", "-m", "etl"]