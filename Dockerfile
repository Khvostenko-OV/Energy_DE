# Pipeline container image (issue #13).
#
# Wraps the existing `python -m etl` CLI unchanged — no pipeline code changes.
# The raw data set and connection settings are NOT baked in: they live in the
# detached named volume mounted at /app/data at runtime (seeded once per
# machine, see scripts/seed_data_volume.sh and docs/containerization.md). The
# entrypoint sources /app/data/docker.env so the CLI can build its engine.

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY etl/ ./etl/
COPY docker/entrypoint.sh /usr/local/bin/etl-entrypoint
RUN chmod +x /usr/local/bin/etl-entrypoint

STOPSIGNAL SIGINT

ENTRYPOINT ["etl-entrypoint"]
CMD ["python", "-m", "etl"]