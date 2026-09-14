# Code review — Load core.storages (issue #7)

- **Date:** 2026-09-15
- **Fixed point:** `c3fe369` (HEAD, `feat: report bad rows dropped in load summary`) — pre-commit review of the uncommitted working tree
- **Diff:** `git diff HEAD` — 5 modified + 1 new file, 535 insertions / 149 deletions (etl/load.py refactor + etl/verify.py `_verify_load_storages` + etl/db_utils.py `_create_core_storages` + CLI wiring + tests/test_load_storages.py new)
- **Commits:** none (uncommitted working tree)
- **Reviewed artifacts:** `_CoreKind` load-path parameterization of etl/load.py (`load_generators` + new `load_storages`, incremental upsert, close-location / region-null / onshore-in-sea / storage-capacity collision checks, collision + `close_to` annotation, property transfer), `_create_core_storages` + `storage_properties` / `storage_units_properties` (db_utils.py), `_verify_load_storages` (verify.py), `load` CLI running both kinds (__main__.py), `STORAGE_CAPACITY_COLLISION_REASON` (db_schema.py), integration test suite (tests/test_load_storages.py)
- **Spec source:** GitHub issue #7 (fetched via `gh issue view 7`), TechnicalSpecification.md (Core, Load), docs/adr/0001-core-unit-identity.md, docs/adr/0005-quality-annotations-as-property-links.md, docs/adr/0006-per-kind-property-link-tables.md, CONTEXT.md
- **Standards sources:** AGENTS.md + CONTEXT.md + ADRs + TechnicalSpecification.md + existing etl/*.py conventions + Fowler smell baseline (Refactoring ch.3)
- **Context:** full integration suite green (63 tests — 14 transform + 23 generator load + 26 storage load); `python -m etl load` runs both kinds PASS with idempotency. Review of the uncommitted tree; a storage-only OR-precedence bug surfaced by the new tests was fixed before this review (parenthesized capacity filter).
- **Decisions locked with the user:** seams = full integration against dev DB; no typechecker; pytest is the only test runner.

Two-axis review: **Standards** (conformance + smells) and **Spec** (faithful implementation), deliberately kept separate.

---

## Standards

- **Duplicated Code (judgement) — `_verify_load_storages` is a ~130-line clone of `_verify_load_generators`; `_create_core_storages` clones `_create_core_generators`.** Table names swapped, storage source loop fixed to `"storage"`, `storage_capacity` added to the capacity drift. Both must be edited in lockstep → Divergent Change. **Accepted as the repo's established per-kind ownership split** (transform owns its per-source verify; the generator review accepted "stage-owns-its-verify" as inherent). `_CoreKind` is the seam if a third unit-kind ever lands, but collapsing the DDL/verifier now would touch already-green generator code for no current need — Speculative Generality cut.
- **Partial parameterization (judgement) — `_load` is fully shared, but `create_table` and `verifier` ride in `_CoreKind` as callables; a third unit-kind would touch load.py + db_utils.py + verify.py + __main__.py (Shotgun Surgery).** The two heaviest per-kind bodies are deliberately left per-kind; the callable seam is where they'd collapse.
- **Repeated Switches (judgement) — `if kind.check_storage_capacity:` gates the extra collision check.** A per-kind tuple of check functions would generalize `_detect_collisions`; the boolean is the minimal reading today (storage is the only kind with the check).
- **Mysterious Name (judgement) — `STORAGE_CAPACITY_COLLISION_REASON = "storage_capacity <= 0 or null"` reads like a code expression where sibling collision values are prose.** Kept: it is the spec's literal phrasing and matches the transform quality-reason style (`"installed_capacity <= 0"`, `"installed_capacity is null"`).
- **Tests mirror test_load_generators.py almost verbatim (~628 lines).** Accepted as the prescribed mirror given the two kinds share their load semantics.
- **Not flagged:** SQL-via-f-strings with schema constants, report/try-except/summary shape, `_`-prefixed helpers, integration-only testing all match existing conventions.

## Spec

- **(a) Faithful.** All six ACs satisfied: storage shape (serial PK, `storage_type`, `storage_capacity` DOUBLE PRECISION, `collision` default false, secondary_attributes, point geometry + longitude/latitude), duplicate-free `(energy_source, reference_id)`, in-place fresher-update / staler-skip / unmatched-insert, property links refreshed on update, the four collision checks with descriptive `collision` / `close_to` annotation, and reconciliation/idempotency verification.
- **(a) `close_to` lives in `secondary_attributes`, not property links.** ADR 0005's "property links (`collision`, and `close_to` …)" is implemented in the established generator interpretation (commit 59c3d34): neighbours in the json `close_to` key, only `collision` as a property link. Consistent in-repo.
- **(a) Region-null "outside" marts bucket** is #9's scope, not #7's; no code expected here.
- **(b) Minor scope — generic `_load(kind)` refactor** rewrote the generator path to share it with storages; the issue asked only for the storage consolidation but "same amended v2.3 load semantics as generators" makes the shared load path the honest reading. The `installed_capacity` drift gate and stray-properties gate in `_verify_load_storages` exceed the AC's literal "counts/capacity reconcile" but mirror the generator verifier.
- **(c) `onshore_sources=("storage",)` with reason "onshore unit in the sea"** flags sea-region storages under a phrase born for bio/gas/hydro/solar. Issue-mandated (AC lists onshore-in-sea for storages); never fires on the real data (0 sea-region storage rows).
- **(c) Test `test_updated_unit_links_refresh` "restore and re-load to reset core state" is a no-op** — restoring the older reference_date makes the re-load skip (staler), so core keeps the 2999-test values. Test hygiene only; identical to the existing generator test, no functional impact.
- Implementation notes: `storage_capacity` is stored `DOUBLE PRECISION` (spec v2.3.1 float row wins over the briefly-`str` v2.3 row), first load gates on `bad_quality=false`, no upstream-removal detection, partial unique index on `(energy_source, reference_id)` — all per issue.

---

## Summary

- **Standards:** 5 judgement calls, worst is the per-kind `_verify_load_storages` / `_create_core_storages` duplication (accepted as the repo's per-kind ownership pattern; `_CoreKind` is the seam to collapse it for a future kind).
- **Spec:** all acceptance criteria met; 2 minor scope additions and 2 judgement notes, worst is the `close_to`-in-jsonb interpretation that predates and governs this work.