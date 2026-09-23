# Code review — slim Python images (distroless multistage) + fat_compose.yaml (issue #34)

- **Date:** 2026-09-23
- **Fixed point:** HEAD (`23c8ea2`) — uncommitted working tree
- **Diff:** `git diff HEAD` + untracked `docker/entrypoint.py`, `tests/test_entrypoint.py`
- **Reviewed artifacts:** `Dockerfile` + `Dockerfile.viz` (Chainguard distroless multistage,
  `/venv` builder → non-root runtime), `docker/entrypoint.py` (new; replaces
  `docker/entrypoint.sh`, which is deleted), `tests/test_entrypoint.py` (new),
  `compose.yaml` → `fat_compose.yaml` (git mv, content kept), `scripts/smoke_etl_container.sh`
  (exported `COMPOSE_FILE`, python `exec` check of `docker.env`), `scripts/seed_data_volume.sh`
  (`chmod -R a+rX /data`), `docs/containerization.md`, `docs/remote-deploy.md`, `README.md`,
  `AGENTS.md`, `.env.example`, `docker/nginx.conf`
- **Spec:** issue #34 (slim images 661MB/1.04GB → multistage Chainguard distroless; entrypoint
  `.sh`→`.py` behavior-identical; `compose.yaml`→`fat_compose.yaml` + reference updates;
  distroless docs; verification = build sizes + smoke + spot checks + native-wheel gate)

## Standards

**No hard violations.** pytest-only, plain class+monkeypatch fixtures, module docstrings —
all conform. The Dockerfile comment "entrypoint.py carries the +x bit in the build context" is
true (host mode `-rwxr-xr-x`, `COPY` preserves it); runtime stages correctly have no `RUN`;
`execvp` keeps the real process as PID 1 for `STOPSIGNAL SIGINT`. The Python entrypoint matches
the shell original's gate exactly (load `docker.env` iff `DATA_ENV_FILE` set + `isfile` + both
URLs unset; operator URL wins). Findings are judgement calls:

- **Dead file (Refused Bequest/Duplicated Code)** — `docker/entrypoint.sh` stayed tracked with
  nothing referencing it. → Fixed: deleted in this change.
- **Long inline predicate (smoke)** — `docker compose exec -T viz python -c "..."` replacing
  `grep -q` is a wall of text, but unavoidable in a shell-less image through the same exec path.
- **Moving target base** — `latest`/`latest-dev` (3.14) is unpinned; the venv-per-build pattern
  absorbs it and remote-deploy.md documents the `python:3.12-slim` fallback.

## Spec

**All five scope items implemented and verified.** Deviations signposted:

- Native-wheel gate passed on wolfi/glibc (pipeline + viz requirement sets install with
  `--only-binary=:all:`; pyogrio/shapely/psycopg2/numpy/pyarrow all manylinux). Smoke passed on a
  genuinely fresh stack (containerized run-all → marts incl. `outside` → `viz_reader` TCP reads →
  viz `/_stcore/health`); spot checks (`transform wind`, `marts`) passed. Sizes: pipeline
  484MB (target ≈410MB, from 661MB), viz 831MB (target ≈740MB, from 1.04GB) — above estimate
  because the Chainguard base is heavier than `python:3.12-slim` and the now-current 3.x/25.x
  wheels are larger, but the distroless goal holds.
- **Documented tag deviation** — `cgr.dev/chainguard/python:3.12(-dev)` no longer exists on the
  public registry (versioned tags moved behind paid org access); the free `latest`/`latest-dev`
  (currently Python 3.14) are used, and the rationale is flagged in both Dockerfiles + docs.
  The issue's `python:3.12-slim` fallback was not needed (wheels load on wolfi).
- **`/venv` honoured** initially as `/app/venv` (non-root wolfi user can't write `/`); the
  builder now runs `USER root` so the venv lives at the spec's exact `/venv`; runtime stays
  non-root over a world-readable root-owned venv.

Findings (all addressed):

1. **`docker/entrypoint.sh` never deleted** — left a stale twin of the entrypoint logic.
   → Fixed: removed; only historical `docs/reviews/*.md` mentions remain.
2. **Smoke "unaffected" claim was near-miss** — the issue said the smoke "pins
   `local_compose.yaml`", but `COMPOSE_FILE` was never `export`ed, so docker compose silently
   used the default `compose.yaml`; the rename removed that file and broke the smoke. This is a
   latent pre-existing bug the rename surfaced. → Fixed: `export COMPOSE_FILE`.
3. **Smoke `docker compose exec -T viz grep`** cannot exist in a shell-less image.
   → Replaced with an equivalent `exec viz python -c` check of the seeded `docker.env`.
4. **Non-root runtime cannot read seeded data** — `docker cp` preserves host `0600` modes on the
   private `.gpkg` files; uid 65532 got "Permission denied" on the first smoke run.
   → `scripts/seed_data_volume.sh` now runs `chmod -R a+rX /data` after seeding (distroless
   implication, documented).

**Summary:** Standards — 0 hard, 4 judgement calls (1 fixed); worst, the dead
`entrypoint.sh` (fixed). Spec — 0 missing, 0 substantive scope creep, 4 fixed look-wrong items;
worst, the un-exported `COMPOSE_FILE` that broke the smoke under the rename (fixed).