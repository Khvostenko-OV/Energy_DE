# Code review — Marts materialized views (issue #9)

- **Date:** 2026-09-15
- **Fixed point:** `6f0f6e5` (HEAD, `Edit permissions`) — pre-commit review of the uncommitted working tree
- **Diff:** `git diff HEAD` — 4 modified + 2 new files, 113 tracked insertions (etl/__main__.py CLI `marts` + run_all hook, etl/db_schema.py `MARTS_SCHEMA`/`OUTSIDE_REGION`, etl/reports.py `MartsReport`, etl/verify.py `_verify_marts`) + new etl/marts.py and tests/test_marts.py (~460 test lines)
- **Commits:** none (uncommitted working tree)
- **Reviewed artifacts:** `_MartDefinition` + `MART_DEFINITIONS` (three materialized-view pivots at region grain, active-only predicate, COALESCE outside bucket), `build_marts` / `verify_marts` / `_create_marts` / `_refresh_marts` (marts.py), `_verify_marts` two-sided EXCEPT set-difference drift check (verify.py), `MartsReport` with per-view refresh timing + summary (reports.py), `python -m etl marts` CLI raising `SystemExit(1)` on drift and run_all hook (__main__.py), integration test suite tests/test_marts.py
- **Spec source:** GitHub issue #9 (fetched via `gh issue view 9`), TechnicalSpecification.md (Marts), docs/adr/0003-marts-as-stored-wide-pivots.md, CONTEXT.md
- **Standards sources:** AGENTS.md + CONTEXT.md + ADRs + TechnicalSpecification.md + existing etl/*.py conventions + docs/reviews/ house style + Fowler smell baseline (Refactoring ch.3)
- **Context:** full integration suite green (121 tests); `python -m etl marts` runs PASS with `Created`/`Refreshed`/refresh-times/`Verified`/`Status`, second run idempotent (`Created: none`). The sqlalchemy/spec-server quirks surfaced by the new tests: `information_schema` does not list materialized views (use `pg_matviews`); `FULL JOIN` is not supported for this comparison (use EXCEPT set-difference); an `ACTIVE AND region IS NULL` test filter initially parsed as `A OR (B AND …)` losing the region gate.
- **Decisions locked with the user:** seams = full integration against dev DB (`etl.marts` API, not CLI); no typechecker; pytest is the only test runner.

Two-axis review: **Standards** (conformance + smells) and **Spec** (faithful implementation), deliberately kept separate.

---

## Standards

- **No documented-standard violations.** House style respected: f-string SQL via schema constants, `_`-prefixed helpers, report/try-except/`summary()` shape, `MartsReport` mirrors `LoadReport`, glossary terms (`region`, `active units`, `source_type`), `MARTS_SCHEMA`/`OUTSIDE_REGION` in the `db_schema.py` constants cluster.
- **Near-miss (judgement) — `run_all` now auto-runs `marts`**, while ADR 0003 says the marts are "refreshed **on demand** by the CLI rather than managed by pipeline code". Auto-refresh on the aggregate `run-all` sits at the boundary of what the ADR rejected. Re-affirmed consciously: `python -m etl marts` remains the only direct trigger; `run-all` is a convenience that treats marts like the other stages.
- **Mysterious seam (judgement) — marts ↔ verify split.** `marts.py` imports `_verify_marts` from `verify.py` at runtime; `verify.py` imports `_MartDefinition` only under `TYPE_CHECKING` to dodge an import cycle. The two-sided EXCEPT drift SQL is built inside `_verify_marts` by reaching into `defn.pivot/value/select_sql`; moving that onto `_MartDefinition` (e.g. a `drift_sql()`) would collapse the seam and kill the type-level cycle. The public `verify_marts(engine)` is pure delegation → mild **Middle Man**. Accepted for now: the type-level cycle is phantom (type-check only), and the split matches `verify.py` owning reconciliation.
- **Feature was fixed during review:** the duplicated `name` field on `_MartDefinition` (redundant with the dict key, a future key/field desync hazard) was removed, and `GROUP BY region` was made explicit as `GROUP BY COALESCE(region, 'outside')` — the old form depended on PostgreSQL preferring the input column name over the output alias, which coincided with the desired grouping only by name collision.
- **Repeated Switches / duplication — not triggered:** `_verify_marts` is the definition-driven antidote to the `_verify_load_generators`/`_verify_load_storages` clone (accepted last review); driven by `MART_DEFINITIONS`, no per-kind bodies.
- **Minor (judgement):** `MartsReport.verified` vs inherited `passed` overlap — a skipped/errored run shows both `Verified: no` and `Status: FAIL` redundantly.
- **Not flagged:** the SQL re-derived inside test_marts.py is *deliberate* — an independent cross-check since `_verify_marts` reuses `select_sql` verbatim and cannot catch a wrong definition.

## Spec

- **(a) Faithful.** All five ACs satisfied: three `CREATE MATERIALIZED VIEW`s at region grain (`marts.py:52–95`); generation keyed by `energy_source`, storage by `source_type` (from `storage_type`, `marts.py:88`); active-only predicate `decommissioning_date IS NULL OR > CURRENT_DATE` (`marts.py:48`); COALESCE outside bucket per definition (`marts.py:56,72,84`); `python -m etl marts` refreshes all three and reports per-view timing (`__main__.py:121–130`), non-zero exit + `Status: FAIL` on drift (`__main__.py:131`). No extra roll-up views added.
- **(a) Verification AC proven for all three pivots** — the drift test was strengthened during review: `test_verify_fails_on_unrefreshed_core_change` now inserts both a generator and a storage probe and asserts each of `installation_counts`, `generation_capacity`, and `storage_capacity` appears in the errors (previous form only covered the two generator marts; a storage-only drift would have passed silently).
- **(a) Outside-bucket semantics** are covered both by dedicated probe tests (`TestOutsideBucket`, including generation/storage capacity via `TestContent` assert against independent SQL) and by the full CONTENT tests that reconcile the COALESCE'd pivots against hand-written expected queries in `test_marts.py`.
- **(b) Minor scope (benign):** public `verify_marts()` (thin wrapper, used by tests) and `MartsReport.created`/`refreshed` lists (beyond the requested timing) — both documentation-friendly, neither overreach.
- **(c) No wrong-but-green implementation found.** The only hazard was `test_outside_cells_match_region_null_core_rows`'s expected SQL, whose `{ACTIVE} AND region IS NULL` parsed as `A OR (B AND …)` and counted all never-decommissioned units (30995 wind vs true 1) — a **test bug**, fixed by parenthesizing the predicate; the mart itself was correct. Worth remembering that `_verify_marts` shares `select_sql` with production, so only independent test SQL can catch definition errors.

---

## Summary

- **Standards:** no hard violations; 4 judgement calls, worst is the marts↔verify type-level seam (accepted; a `drift_sql()` on `_MartDefinition` is the future collapse point). Two findings fixed during review (dropped redundant `name` field; explicit COALESCE grouping).
- **Spec:** all five acceptance criteria met; 2 benign scope additions; the drift-verification AC was strengthened to cover all three pivots after review, and one test-side SQL precedence bug was fixed.