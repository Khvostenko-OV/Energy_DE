# Remote deployment (issue #13)

Step-by-step for deploying the containerized ETL stack (pipeline image + PostGIS
compose + data-volume seed, `docs/containerization.md`) on a remote server. The
server only needs Docker — nothing private (raw data, connection settings) is
cloned or committed; it is transferred and seeded per machine.

## 0. Prereqs

- Linux server (x86_64/amd64 recommended — the official `postgis/postgis`
  image is amd64-only; on ARM it runs under emulation, which works but is
  slower)
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

On the server, confirm the manifests came along:

```bash
ls data/sources/sources.txt data/boundaries/boundaries.txt
```

## 4. Set credentials

The defaults are `etl`/`etl`. The compose `POSTGRES_*` variables and the seed
script's `DB_*` variables are a coupled pair — they must match. Set both before
building/seeding:

```bash
export POSTGRES_USER=etl POSTGRES_PASSWORD='<you-know>'
export DB_USER=etl DB_PASSWORD='<you-know>'
```

## 5. Build image + seed the data volume (once per machine)

```bash
docker compose build pipeline
./scripts/seed_data_volume.sh     # creates etl_data volume: raw data + docker.env
```

## 6. Start PostGIS and run the pipeline

```bash
docker compose up -d --wait db    # waits until the DB really accepts TCP
docker compose run --rm pipeline  # python -m etl run-all; non-zero exit = loud failure
```

One-shot alternative:

```bash
docker compose up --build --abort-on-container-exit --exit-code-from pipeline
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
ufw. (Metabase, when it joins the stack in #15, talks to `db` over the compose
network and needs no host-exposed port.)

```bash
sudo ufw default deny incoming
sudo ufw allow 22/tcp
# no rule for 5433 = DB reachable only from the server
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