# Containerized ETL (issue #13)

The existing CLI pipeline (`python -m etl`) runs unchanged inside containers —
**no pipeline code changes**. This is pure packaging: a pipeline image that
wraps the CLI, a Docker Compose stack that provisions PostGIS, and a
documented one-time manual seed procedure that puts the private raw data set
and connection settings into a detached volume the pipeline reads.

> **CLI naming:** the pipeline's `run_all` stage is exposed by Click as the
> command `run-all` (Click verbatim-keeps single-word names and hyphenates
> multiword function names). This is true of the host CLI too — the image
> behaves identically to the host run. The container and everything below use
> `run-all`; `etl/__main__.py` names the Python function `run_all`.

## Architecture

```
 host machine (docker)
 ├─ data/sources/*.gpkg, data/boundaries/*.gpkg   (private, git-ignored)
 ├─ scripts/seed_data_volume.sh  ── once per machine ──►  volume: etl_data
 │                                                       (data + docker.env)
 ├─ compose.yaml:  db (imresamu/postgis)                ┐ network
 └─ compose.yaml:  pipeline (build .; `python -m etl run-all`) → db service
```

| What | Where |
|------|-------|
| Pipeline image | built from this repo (`Dockerfile`), exposes `python -m etl` unchanged |
| PostGIS database | `db` service; PostGIS extension enabled by the image on first init |
| Raw data + connection settings | detached named volume `etl_data`, seeded once per machine |
| Volume mount | `etl_data` → `/app/data` (so `run-all`'s `data/sources/...`, `data/boundaries/...` resolve) |

The image never contains data or connection settings. `etl/config.py` reads
`DATABASE_URL` from the environment; the container entrypoint
(`docker/entrypoint.sh`) sources `/app/data/docker.env` from the seeded volume
before handing control to the CLI. Nothing data- or secret-like is baked in.

> **Platform note:** the `db` image is a multi-arch build
> (`imresamu/postgis`, arm64 + amd64), so the database runs natively on both
> Apple Silicon and x86 servers — the official `postgis/postgis` images are
> amd64-only and would otherwise run under emulation on ARM. The pipeline
> container itself is native `arm64`.

## One-time seed (per machine)

Prerequisites: docker; the private raw data set present under `data/sources/`
and `data/boundaries/` (including the `sources.txt` / `boundaries.txt`
manifests).

```bash
scripts/seed_data_volume.sh          # defaults to volume `etl_data`
# or with ENV:  ETL_DATA_VOLUME=etl_data scripts/seed_data_volume.sh
```

What it does (idempotent, safe to re-run):

1. creates the named volume `etl_data` if absent,
2. copies `data/sources/` and `data/boundaries/` into it,
3. writes `/data/docker.env` with `export DATABASE_URL=postgresql://…@db:5432/…`.

A fresh machine is then self-contained — the raw data and connection settings
ride in the volume, not in git or the image.

## Run the pipeline

```bash
docker compose up --build            # builds image, runs the full pipeline (run-all)
```

The full pass runs extract → transform → load → marts against the compose
`db` service, verifying every stage; the marts stage reconciles the stored
pivots to core and **fails loudly (non-zero exit) on drift**.

The image exposes the same CLI as the host, so any single stage works too (with
`db` up):

```bash
docker compose up -d --wait db                      # ensure db is healthy
docker compose run --rm pipeline python -m etl marts
docker compose run --rm pipeline python -m etl transform wind
```

`DATABASE_URL` comes from the seeded volume. `run-all` is the default command,
so a bare `docker compose run --rm pipeline` runs the pass too.

## Verify the marts

```bash
docker compose exec -T db psql -U etl -d energy_de -c "SELECT * FROM marts.installation_counts ORDER BY region LIMIT 8"
```

The three materialized views exist in schema `marts` at region grain
(`installation_counts`, `generation_capacity`, `storage_capacity`); units with
no region fall under the `outside` bucket rather than `NULL`.

## Automated smoke check

`scripts/smoke_etl_container.sh` proves the acceptance criteria on a genuinely
fresh stack: teardown → seed → healthy PostGIS → containerized `run-all` →
mart assertions (three views exist, non-empty, no NULL regions, `outside`
bucket present). Re-run it any time the packaging changes:

```bash
scripts/smoke_etl_container.sh
```

## Configuration

| Env var | Default | Meaning |
|---------|---------|---------|
| `ETL_DATA_VOLUME` | `etl_data` | detached volume holding data + `docker.env` (compose + seed) |
| `POSTGRES_USER` | `etl` | db superuser (compose `db`) |
| `POSTGRES_PASSWORD` | `etl` | db password (compose `db`) |
| `POSTGRES_DB` | `energy_de` | default database, PostGIS enabled there |
| `POSTGRES_PORT` | `5433` | host port for the db (5432 is the in-network/default dev port) |
| `DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT`/`DB_NAME` | `etl`/`etl`/`db`/`5432`/`energy_de` | what the seed script writes into `docker.env` (for the pipeline) |

The compose `POSTGRES_*` credentials and the `DATABASE_URL` the seed writes are
a coupled pair: if you change `POSTGRES_PASSWORD`, change the seed env
accordingly and re-run `scripts/seed_data_volume.sh`.

## Teardown / start over

```bash
docker compose down --remove-orphans   # stop and remove containers + network
docker compose down -v                 # also delete the db data volume (fresh db)
```

The data volume is deliberately **external to compose** (`external: true`), so it
*detaches* — `down -v` removes the db volume but leaves `etl_data` intact
(that's what makes the seed "once per machine"). To reset the data volume too:

```bash
docker volume rm "${ETL_DATA_VOLUME:-etl_data}"   # drop the detached data volume
scripts/seed_data_volume.sh                       # re-seed
```

Re-seeding in place also works — `seed_data_volume.sh` overwrites the volume
contents, so `seed → up` is a complete runnable cycle on top of an existing
seed. Re-running `docker volume create` is idempotent.

## Tickets

- #13 this containerization
- #14 CI smoke gates (compile check + pipeline image build) — blocked by #13
- #15 Metabase joined to this compose stack — blocked by #13
- #16 full-stack verification seam (one command) — blocked by #13, #15