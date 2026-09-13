# Code review — Transform align to spec v2.2 (issue #11)

- **Date:** 2026-09-14
- **Fixed point:** `f45aa4e` (Tech Specification v2.2) — review of the uncommitted working tree
- **Diff:** `git diff HEAD` — 8 tracked files, 109 insertions / 34 deletions, plus untracked `tests/test_transform_v22.py` and `requirements-dev.txt`
- **Commits:** none (uncommitted working tree)
- **Reviewed artifacts:** staging `secondary_attributes` column (DDL + STAGING_COLUMNS), whitelist decomposition (`DECOMPOSED_PROPERTIES`, `_decompose_attributes`, `_reduce_secondary_attributes`), region-null gate removal from `_quality_reasons`, verify whitelist-drift checks, integration test suite + pytest dev requirement
- **Spec source:** GitHub issue #11 (`gh issue view 11`), TechnicalSpecification.md (Transform / Staging / core sections), CONTEXT.md, ADR 0005 (spec v2.2 amendment)
- **Standards sources:** AGENTS.md + existing `etl/` module style (db_schema.py single home for schema constants, verify.py fail-loudly checks) + Fowler smell baseline (Refactoring ch.3)
- **Context:** verified against live PostGIS — full integration suite (14 tests) transforms all six sources and PASSes. Two-axis review; findings were review-era and mostly fixed before commit.
- **Decisions locked with the user:** seams = full integration against the dev DB; no typechecker for now.

Two-axis review: **Standards** (conformance + smells) and **Spec** (faithful implementation), deliberately kept separate. Review-era findings that were fixed in the same pass are marked `[fixed]`.

---

## Standards

- **Duplicated Code — whitelist defined twice.** `DECOMPOSED_PROPERTIES` (db_schema.py) and the test module's `WHITELIST` literal were the same 14 keys. Drift between them silently changes the contract. *[fixed] Tests now import `DECOMPOSED_PROPERTIES`.*
- **Duplicated Code, divergent implementations — "no leaked keys" check twice.** verify.py string-scanned `LIKE '%"<key>"%'` per key (14 connections, fragile: matches a quoted whitelisted key inside a *value*, which would false-fail AC#1); the tests used `jsonb_object_keys(...::jsonb)`. *[fixed] verify now uses the jsonb key-membership operator `?| ARRAY[...]` in a single query, checking keys only.*
- **Mysterious Name — nested `strip`.** Vague verb, the only undocumented function in the module. *[fixed] Renamed `drop_whitelisted`, documented.*
- **Message accuracy — `leaked` sum.** Per-key row counts summed row-occurrences, not rows. *[fixed] Superseded by the single `?|` row count.*
- **Duplicated Code — empty-bag guard.** The `("", "{}")` guard + `json.loads(...).items()` shape recurring in `_decompose_attributes` and `_reduce_secondary_attributes`. *[fixed] Shared `_safe_attributes` helper; also closes the pre-existing `json.loads("nan")` crash hole flagged on the Spec axis.*
- **Not flagged:** no comments added (AGENTS.md "no comments" rule kept); `DECOMPOSED_PROPERTIES` correctly homes in db_schema.py; storage keeps `technology` decomposed with the rest of the whitelist; no hard documented-standard violations.

## Spec

Reviewed against issue #11 + TechnicalSpecification.md (Transform / Staging) + ADR 0005. All four issue requirements are correctly implemented:

- `secondary_attributes` re-added to all six staging tables (db_utils.py DDL + STAGING_COLUMNS).
- Whitelist decomposition — exact 14 keys, `technology` on storage included; non-whitelist keys (`biogas_unit`, `chp_unit`, `area_id`, `turbine_type`) stay in the json.
- No duplication — `_decompose_attributes` reads the unreduced json, then `_reduce_secondary_attributes` strips whitelisted keys before the row written to staging.
- Region-null gate dropped from `_quality_reasons`; null-region rows pass staging unflagged.

- **(a) "Reconcile against the previous transform" is asserted by literals, not by diffing runs.** `EXPECTED_BAD_QUALITY`/`EXPECTED_REGION_NULLS` hardcode the pre-v2.2 observed counts (e.g. solar 12, region-nulls hydro 15 / solar 5 / wind 1 / storage 30). These literals are an independent source of truth (measured from the old DB state), not recomputed by the code — the reconciliation AC is honoured in spirit by asserting the exact transition (51 region-null rows now unflagged). Accepted.
- **(b) Scope beyond the work order:** the test suite + `requirements-dev.txt` (pytest) and `.gitignore` `.pytest_cache/` — requested by the user's "use /tdd at pre-agreed seams" instruction; the two new verify invariants follow the repo's established fail-loudly pattern. Accepted; not creep.
- **(c) `_reduce_secondary_attributes` / `_decompose_attributes` shared pre-existing crash hole** — a stored value whose repr is `nan` passes the old empty-guard and `json.loads("nan")` yields a float, crashing `.items()`. *[fixed] `_safe_attributes` parses defensively; real extract drops NaN values, so no live data hits it.*
- **(c) Region-null → `collision` promise lives at load, not here.** The tests assert the staging guarantees only (`region IS NULL AND bad_quality = 0`); the ADR/CONTEXT promise that these rows get a core `collision` link is a #6/#7 load-side follow-up, correctly out of scope for #11. Noted, no action.

**AC cross-check:** staging-shape ACs (secondary_attributes present; properties = whitelist exactly; whitelist keys absent from json; region-null not bad) all enforced by tests AND the two new verify gates that fail loudly on drift.

---

## Summary

- **Standards — 5 findings, all judgement calls/smells, all fixed.** Worst: the failed-to-drift-guarantee duplicated whitelist. No hard documented-standard violations.
- **Spec — 3 findings (1 accepted literal-reconciliation, 1 accepted user-requested scope, 1 fixed crash hole).** Worst: the pre-existing `nan`-parse crash hole (fixed) — the four issue requirements themselves are correct end-to-end.