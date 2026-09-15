# Code review — Core dimension tables + annotation integrity (issue #8)

- **Date:** 2026-09-15
- **Fixed point:** `c77cd73` (HEAD, `Edit permissions`) — pre-commit review of the uncommitted working tree
- **Diff:** `git diff HEAD` — etl/verify.py (per-unit collision-link integrity + value-level reason reconciliation in `_verify_load_generators` / `_verify_load_storages`), etl/db_schema.py (hoisted `REGION_NULL_COLLISION_REASON`, `ONSHORE_IN_SEA_COLLISION_REASON`, `ONSHORE_SOURCES`), etl/load.py (use the hoisted constants), plus untracked new file tests/test_core_dimensions.py
- **Commits:** none (uncommitted working tree)
- **Reviewed artifacts:** `_verify_load_generators` / `_verify_load_storages` collision-annotation checks, hoisted collision-reason constants in db_schema.py and their adoption by load.py, and the new issue-#8 integration suite (reconciliation, per-unit collision integrity, negative drift, FK-orphan rejection, fail-loudly load, refresh-on-update)
- **Spec source:** GitHub issue #8 (fetched via `gh issue view 8`), TechnicalSpecification.md (Core, Verify), docs/adr/0001-core-unit-identity.md, docs/adr/0005-quality-annotations-as-property-links.md, docs/adr/0006-per-kind-property-link-tables.md, CONTEXT.md
- **Standards sources:** AGENTS.md + CONTEXT.md + ADRs + TechnicalSpecification.md + existing etl/*.py and tests/*.py conventions + Fowler smell baseline (Refactoring ch.3)
- **Context:** full integration suite green (101 tests — previously 63 + 38 in the new module). Seams fixed at full integration against the live dev PostGIS; no typechecker installed (pytest is the only runner, consistent with prior reviews). Issue #8's mechanics (per-kind property tables, staging-whitelist transfer, refresh-on-update, count verification) landed in earlier commits (f83bc49, 98b3a62, f2aa6f8); this review covers the working-tree delta that closes the ticket's cross-table / annotation-integrity acceptance criteria, TDD'd: red negative tests first, then the verifier strengthen.

Two-axis review: **Standards** (conformance + smells) and **Spec** (faithful implementation), deliberately kept separate.

---

## Standards

- No documented-standard violations. Both hunks implement ADR 0005's flag↔link contract with the ADR 0006 per-kind tables; names `missing_link` / `stale_link` reveal purpose; the reason-value `NOT LIKE` checks read honestly; the hoist of reason strings and `ONSHORE_SOURCES` into db_schema.py strengthens the module's single-home-for-constants role and removes the load.py/verify.py literal-duplication coupling.
- **Duplicated Code (judgement, convention-sanctioned) — the two verify hunks are per-kind clones, tables swapped.** Precedent review `code-review-load-core-storages-20260915.md` accepted per-kind verify duplication as the "stage-owns-its-verify" split; the reason-check loop is the same shape in both kinds with only the table names and capacity/onshore conditions differing. Accepted, `_CoreKind` is the documented seam for a future third kind.
- **Data Clumps / Repeated Switches (judgement) — tests pass the `(table, props, links)` kind triple around and discriminate via `kind[0] == "generators"`.** A `_CoreKind`-style bundle carrying the verifier/loader would remove the string compares. Judgement only: mirror of the sibling suites' explicitness.
- **Duplicated Code across modules (judgement) — the harness (`_ensure_staging` / `_drop_core` / `_loaded_core` / `_staging_ready`) is re-cloned from both load suites; `test_no_orphaned_links` and `test_bad_quality_absent_from_core` repeat sibling assertions.** Partly justified (the module owns the *cross-table* view the siblings lack); a conftest.py fixture would gather the harness. Leave for a future refactor.
- **Mysterious Name (micro) — `test_verifier_flags_whitelist_link_drift` asserts the loose substring `"link" in e`.** Works but the assertion intent is fuzzy; accepted as a negative-test convenience.
- **Not flagged:** SQL-via-f-strings with schema constants, report/errors shape, `_`-prefixed helpers, integration-only testing all match existing conventions.

## Spec

- **(a) Faithful.** All five ACs are now closed by this delta plus the earlier committed mechanics:
  - `core.properties` / `core.units_properties` exist per kind (ADR 0006 naming supersedes the ticket's shared-table names) and serve both unit-kinds — `test_core_dimensions.py` asserts the whitelist-only dimension and exact property-set / link-count reconciliation against the staging decomposition for both kinds.
  - No link references a missing `unit_id` (FK enforced + `test_orphaned_link_rejected_by_schema`; no-orphan counts; refresh-on-update test adds/removes a staging whitelist pair and asserts core relinks/unlinks).
  - `bad_quality` absent from core; collision links present **and correct** for every `collision=true` row — per-unit directional checks (`missing_link` for `collision=true` rows, `stale_link` for `collision=false` rows, region-null rows carried) plus a value-level reconciliation that every region-null / onshore-in-sea / close-location / (storage) capacity-invalid row's collision link value names that reason.
  - Cross-table verification passes and fails loudly on drift — negative tests inject missing/stale/swapped links, `bad_quality` leaks, stripped whitelist links, stripped reason values, and a full no-change `load_*()` run that must return `report.passed == False`.
- **(a) Compensated drift.** The new per-unit checks catch what the old aggregate `flagged != linked` count was blind to: a collision link moved off one flagged row and onto a clean row keeps the totals equal (`test_verifier_flags_compensated_drift` was red against the old check, green after).
- **(b) The revoke-two-different directional checks** ("no `collision=false` row may carry a link") is slightly beyond the AC's literal one-way "present for every `collision=true`", as is the value-level reason reconciliation beyond "counts reconcile". Both are justified by AC4's "present **and correct**" and by the bidirectional flag↔link invariant the loader itself maintains (ADR 0005); not flagged as unwarranted scope.
- **(b) Note on the collision link "correctness" scope:** reason *presence* is verified; an adversarial *extra* reason value on a row is not (the checks are presence-minimal per reason). Consistent with AC4's "present and correct for every collision=true row" reading for this issue; deeper value-set equality is a future hardening.
- Implementation notes: `ONSHORE_SOURCES` and the reason strings hoisted to db_schema.py are the single source for both the loader (writes reasons) and the verifier (checks them), so the checked phrases cannot silently diverge from the written ones.

---

## Summary

- **Standards:** 4 judgement calls (per-kind duplication sanctioned by precedent; test-kind triple; harness re-cloning; one loose assertion), worst is the accepted per-kind verifier/clone duplication.
- **Spec:** all five acceptance criteria met; 2 judgement notes (directional/value checks slightly beyond the literal AC language, both AC-justified); worst, the value-level reconciliation is presence-minimal per reason rather than full value-set equality (deferred hardening).