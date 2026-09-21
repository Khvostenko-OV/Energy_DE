# Remote deployment (issue #13)

Step-by-step for deploying the containerized stack (pipeline image + PostGIS +
Streamlit viz app + data-volume seed, `docs/containerization.md`) on a remote
server. The server only needs Docker — nothing private (raw data, connection
settings) is cloned or committed; it is transferred and seeded per machine.

## 0. Prereqs

- Linux server (x86_64/amd64 or arm64 — the `db` image is multi-arch, so no emulation on either)
- Docker Engine + Compose v2
- A machine that holds the private raw data set (`data/sources`,
  `data/boundaries`)

## 1. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
# log out and back in (or: newgrp docker) so the group takes effect
docker --version && docker compose version
```

## 2. Get the code

```bash
git clone https://github.com/Khvostenko-OV/Energy_DE.git
cd Energy_DE
```

No `.env` is needed on the server — the connection settings live in the seeded
volume (`etl_data:/app/data/docker.env`).

## 3. Transfer the private raw data

The data is git-ignored, so it must be copied from the machine that holds it:

```bash
scp -r data/sources data/boundaries user@server:/path/to/Energy_DE/data/
```

On the server, confirm the data came along:

```bash
ls data/sources data/boundaries/boundaries.txt
```

## 4. Set credentials

The defaults are `etl`/`etl`. The compose `POSTGRES_*` variables and the seed
script's `DB_*` variables are a coupled pair — they must match. Set both before
building/seeding; the viz role password defaults to `viz` in both
`docker/viz_reader.sql` (the DB-side provisioning) and the seed. Set both
before building/seeding if you deviate:

```bash
export POSTGRES_USER=etl POSTGRES_PASSWORD='<you-know>'
export DB_USER=etl DB_PASSWORD='<you-know>'
```

## 5. Build images + seed the data volume (once per machine)

```bash
docker compose build pipeline viz
./scripts/seed_data_volume.sh     # creates etl_data volume: raw data + docker.env
```

## 6. Start PostGIS, run the pipeline, reach the viz app

```bash
docker compose up -d --wait db    # waits until the DB really accepts TCP
docker compose run --rm pipeline  # python -m etl run-all; non-zero exit = loud failure
docker compose up -d --wait viz   # healthy Streamlit app, no-auth dashboard
```

A fresh db volume provisions the read-only `viz_reader` role automatically from
`docker/viz_reader.sql` (`/docker-entrypoint-initdb.d`). For a database volume
that predates issue #28, run the seam once by hand:

```bash
docker compose exec -T db psql -U etl -d energy_de -f \
  /docker-entrypoint-initdb.d/99-viz-reader.sql
```

The app (Streamlit + PyDeck, reads the marts/core/service tables as the
read-only role) is then at `http://<host>:8501` with **no auth**.

One-shot alternative for a full pipeline pass:

```bash
docker compose run --rm pipeline
```

Re-runs are idempotent — repeat `docker compose run --rm pipeline` at any time
to refresh the marts from the loaded raw tables.

## 7. Verify the marts (incl. the `outside` bucket)

```bash
docker compose exec -T db psql -U etl -d energy_de -c \
  "SELECT region, count(*) FROM marts.installation_counts GROUP BY 1 ORDER BY 2 DESC LIMIT 6"
docker compose exec -T db psql -U etl -d energy_de -c \
  "SELECT count(*) FROM marts.installation_counts WHERE region='outside'"
```

## 8. Firewall / exposure

`db` publishes `5433:5432` on the host by default. Do not leave Postgres open to
the internet — either add no rule for it, bind it to localhost, or restrict with
ufw. The viz app publishes `8501` and *does* need to be reachable (it is the
entry point for the visualisation), so it gets a rule; in front of it use HTTPS
on a server, or open `8501` only to trusted IPs for a private setup (the app
has no auth by design, per the visualization spec):

```bash
sudo ufw default deny incoming
sudo ufw allow 22/tcp
sudo ufw allow 8501/tcp       # Streamlit viz app (no auth — keep it restricted)
# no rule for 5433 = DB reachable only from the server (the app talks to it
# over the compose network, so it does not need the host port)
sudo ufw enable
```

## 9. Starting over / backups

- Fresh rebuild: `docker compose down -v`, then remove the data volume
  (`docker volume rm etl_data`), re-seed, and `up`.
- Backups: the loaded DB lives in the `energy-de-etl_db_data` volume, the seeds
  in `etl_data`. The simplest durable backup is:

```bash
docker compose exec -T db pg_dump -U etl energy_de > backup.sql
```