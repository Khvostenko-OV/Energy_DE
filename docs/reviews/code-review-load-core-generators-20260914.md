# Code review — Load core.generators (issue #6)

- **Date:** 2026-09-14
- **Fixed point:** `86d2ed4` (HEAD, `docs: align CONTEXT, ADR 0001, README with spec v2.3.1 core shape`) — pre-commit review of the uncommitted working tree
- **Diff:** `git diff HEAD` — 8 files, 374 insertions / 6 deletions (etl/load.py + tests/test_load_generators.py new)
- **Commits:** none (uncommitted working tree)
- **Reviewed artifacts:** `core.generators` DDL + `core.properties` / `core.units_properties` (db_utils.py), `load_generators` + record identity / freshness gate / collision detection + annotation (load.py), `LoadReport` (reports.py), `_verify_load_generators` (verify.py), `load` CLI command (__main__.py), shared `SYNTHETIC_ID_PREFIX` (db_schema.py), integration test suite (tests/test_load_generators.py)
- **Spec source:** GitHub issue #6 (fetched via `gh issue view 6`), TechnicalSpecification.md (Core, Load), docs/adr/0001-core-unit-identity.md, docs/adr/0005-quality-annotations-as-property-links.md, CONTEXT.md
- **Standards sources:** AGENTS.md + CONTEXT.md + ADRs + TechnicalSpecification.md + existing etl/*.py conventions + Fowler smell baseline (Refactoring ch.3)
- **Context:** implementation verified against live PostGIS (full integration suite, 32 tests — 14 transform + 18 load). Review was of the uncommitted tree; findings were fixed immediately afterward.
- **Decisions locked with the user:** seams = full integration against dev DB; no typechecker; pytest is the only test runner.

Two-axis review: **Standards** (conformance + smells) and **Spec** (faithful implementation), deliberately kept separate.

---

## Standards

- **Hard violation — wrong join-table name `generators_properties` instead of `units_properties`.** ADR 0005 (and CONTEXT.md) name the normalized dimension tables `properties` / `units_properties`, a deliberate choice to share one set across the core tables. The diff created `generators_properties` in the DDL, all load SQL, verify SQL, and the tests — a per-source pattern the ADR rejected, and a landmine for issue #7 (storages). **Fixed: renamed to `core.units_properties` (no FK on unit_id — shared by generators and storages, per spec core "double set"; #8 owns link integrity).**
- **Speculative Generality — `_create_core_storages`.** 70 lines of `core.storages` DDL added and never called; storages is #7's ticket and was out of #6 scope. **Fixed: removed.**
- **Duplicated Code (micro) — load report/exit block** repeated in `load()` and `run_all()`. **Fixed: `run_all` now calls the `load` command via `ctx.invoke(load)`.**
- **Duplicated Code (judgement) — reconciliation SQL in tests vs verify.** The tests re-derive expected counts/capacity directly from staging instead of calling `_verify_load_generators`; independent expected values are deliberate test practice, not a defect.
- **Shotgun Surgery (inherent)** — collision logic spans db_schema (constants), load (detection/writing), verify (checks), tests. Same shape as transform's stage-owns-its-verify split; accepted.
- **Not flagged:** SQL-via-f-strings with schema constants, report/try-except/summary shape, `_`-prefixed module helpers all match existing conventions (extract/transform). Promoting `SYNTHETIC_ID_PREFIX` into db_schema is a correct DRY move.

## Spec

- **(a) Partial — decomposed-attribute links deferred.** "Transfer primary keys for dimension tables" (spec §3 Load) and AC "Property links refreshed on update, never orphaned" are only satisfied for the collision annotation the load writes (`collision` / `close_to`), which are fully reset and re-written each run so they never orphan. The 14-key whitelist decomposition relink to serial `unit_id`s is owned by #8 (blocked by #6; its AC "Link counts reconcile exactly to the staging whitelist decomposition"). Scope split is ticket-consistent.
- **(a) Partial — idempotency assert lives in the load, not the verifier.** `load_generators` re-partitions staging after the upsert and asserts no second-pass insert/update; `_verify_load_generators` reconciles counts/duplicates/capacity. The AC "idempotency assert passes" is satisfied via `report.idempotent`.
- **(b) Scope — CLI wiring.** The `load` subcommand + `run_all` integration exceed the AC's letter but are the required plumbing to make `python -m etl load` real (the ticket's stated goal).
- **(c) Close-to value is the other unit's core serial id, as string.** Matches ADR 0005 / CONTEXT ("naming the other unit's id", the core PK), not the reference_id.
- **(c) `geo_accuracy` typed `BIGINT` vs spec `int`** — consistent with the staging DDL; harmless widening.

---

## Summary

- **Standards: 4 findings (1 hard + 3 judgement) — worst: `generators_properties` naming, a hard ADR 0005 breach fixed by renaming to shared `units_properties`.**
- **Spec: 4 finding-groups, all partial/scope/typing judgments — worst: the decomposed-attribute relink explicitly deferred to #8 while #6's AC language claims "property links refreshed", a ticket-scope tension documented here.**