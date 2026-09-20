# Code review — containerize Streamlit viz, drop Metabase (issue #28)

- **Date:** 2026-09-21
- **Fixed point:** HEAD (`defb7a2`) — uncommitted working tree
- **Diff:** `git diff HEAD` + untracked `Dockerfile.viz`, `docker/viz_reader.sql`
- **Reviewed artifacts:** `docker/viz_reader.sql` (new), `Dockerfile.viz` (new),
  `compose.yaml` (viz service + initdb mount, metabase removed), `scripts/seed_data_volume.sh`
  (VIZ_DATABASE_URL), `scripts/smoke_etl_container.sh` (role/idempotency/TCP-read checks,
  health probe, metabase-absent), `docker/entrypoint.sh` (shared entrypoint),
  `docs/containerization.md`, `docs/remote-deploy.md`, `README.md`, `AGENTS.md`,
  `TechnicalSpecification.md` (note)
- **Spec:** issue #28 (AC: standalone viz at 8501 no auth; idempotent `viz_reader` incl.
  dev-host SQL seam + `VIZ_DATABASE_URL`; metabase removed, marts untouched; db+viz smoke
  health probe; doc updates)

## Standards

**No hard violations.** Issue-referenced comments (#13/#28) throughout; coupled-pair
credential framing matches the existing `etl`/`etl` compose precedent and the
containerization doc's own conventions; bash follows the existing
`set -euo pipefail` / `step`/`fail`/`expect_count` shape; the smoke re-uses the same
assert helpers for the new role checks. Findings are judgement calls:

- **Duplicated Code — role/password pair now lives in five places** (SQL seam, seed, smoke,
  both docs). Documented override: the repo's coupled-pair convention *is* this; but the
  smoke initially hard-coded `viz_reader` while the seed exposed `VIZ_USER` — the pairing
  was broken for that one var. → Fixed: smoke now uses `${VIZ_USER:-viz_reader}`.
- **Hard-coded login password in git (`docker/viz_reader.sql` PASSWORD 'viz')** vs. the
  "connection settings … not in git" framing. Judgement call: it is the documented dev
  default, exactly as the pre-existing `etl`/`etl` compose defaults; the doc now says so
  explicitly ("the only credentials in git are the documented dev defaults").
- **Mysterious Name / misleading comment — `docker/entrypoint.sh`:** the comment said
  "unless the operator already supplied the relevant URL" but the gate checks *both*
  URLs empty. → Fixed: comment now states the actual rule.
- **Duplicated Code — `Dockerfile.viz` re-derives the pipeline image's ENV/PIP/COPY block.**
  Documented in its header ("same packaging pattern"); a shared base target would be a
  refactor, not this ticket.
- **Shotgun Surgery (judgement)** — one logical change (read-only role + viz container)
  touches ten files; consistent with how the repo ships infra+docs together.

## Spec

**All five acceptance criteria are implemented and verified** (probed by
`scripts/smoke_etl_container.sh` on a genuinely fresh stack; the app's read path also
exercised as `viz_reader` on the app's exact SQL):

- AC1 viz standalone at 8501 no auth — compose `viz` depends only on healthy `db`,
  headless on 0.0.0.0; `/_stcore/health` → `ok`, app root served.
- AC2 idempotent role + dev-host SQL seam + `VIZ_DATABASE_URL` — `docker/viz_reader.sql`
  creates the role and grants SELECT (default privileges USAGE-on-schemas +
  SELECT-on-tables/sequences, schema-less so the not-yet-existing marts schema is
  covered) plus existing-object grants; re-run verified idempotent; seed writes
  `VIZ_DATABASE_URL`; role read path over TCP (the app's password path) verified.
- AC3 metabase removed from compose; `etl/marts.py` and mart verification untouched.
- AC4/5 smoke health probe + stack-note / containerization docs updated.

Findings:

1. **PG15+ `ON SCHEMAS` default-privilege syntax is un-guarded** — a dev host on PG<15
   would fail that statement. Dev and container are PG17/16 respectively, so current
   stacks are fine; the seam's header now documents the requirement.
2. **Read-only guarantee is env-ordering-dependent** — the viz container also receives
   write-capable `DATABASE_URL` from `docker.env`, and `viz/data.py` falls back to it if
   `VIZ_DATABASE_URL` goes missing. In the stack the seed always writes
   `VIZ_DATABASE_URL`, so the app runs read-only; the fallback is the intended dev-host
   path. → Documented in containerization.md (read-only scope note).
3. **Existing `db_data` volumes predating this issue never run the initdb hook** — the
   role must be provisioned once by hand (documented seam command). Inherent to the
   initdb design; covered by docs.
4. **`docker compose up -d --wait viz` requires the seeded volume** — consistent with
   the stack's nothing-baked-in model; documented.
5. **Metabase still mentioned as the dashboard in `TechnicalSpecification.md`** — the
   spec's tooling predates the Streamlit decision. → Fixed: adds a note to both spec
   locations pointing at `VisualizationSpec.md` / issue #28, without touching the marts
   contract.

**Summary:** Standards — 1 hard-ish (fixed), 4 judgement calls; worst, the five-way
credential duplication with one broken var (fixed). Spec — 0 missing/partial, 0 scope
creep, 5 documented-in-or-fixed look-wrong items; worst, the un-guarded PG15 syntax.
Verified end-to-end by the smoke seam and an in-container `viz_reader` read test.