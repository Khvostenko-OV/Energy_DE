# Code review — Transform all sources incl. offshore + synthetic identity (issue #5)

- **Date:** 2026-09-13
- **Fixed point:** `ae67c33` — post-commit re-review of the committed diff
- **Diff:** `git diff ae67c33...HEAD` — 8 files, 161 insertions / 23 deletions (incl. the prior review doc; 6 `etl/*.py` files carry the code)
- **Commits:** `ea1f85b` feat (all sources), `35e8b57` storage shape into STAGING_COLUMNS, `b5455bc` STORAGE_COLUMNS → db_utils, `f0b94fb` SOURCE_NAMES drive CLI + filename regex, `87b982b` capacity gate split
- **Reviewed artifacts:** storage-aware staging DDL + shared STAGING_COLUMNS, synthetic-identity verification (count/uniqueness/expectation), storage-shape verification, quality-gate split into null / non-positive capacity checks, all-driven-by-SOURCE_NAMES CLI + `run_all`
- **Spec source:** GitHub issue #5 (fetched via `gh issue view 5`), issue #4 (parent/blocker + its "bad_quality never → core" rule), TechnicalSpecification.md, CONTEXT.md, ADR 0001/0005
- **Standards sources:** AGENTS.md + CONTEXT.md + ADRs + TechnicalSpecification.md + prior review `code-review-transform-all-sources-20260913.md` + Fowler smell baseline (Refactoring ch.3)
- **Context:** implementation was verified against live PostGIS (six staging tables, 39 solar synthetic ids, 1,688 offshore wind in sea/EEZ regions, storage shape carried, per-source verify PASS). Code-below check only.
- **Decisions locked with the user:** lowercase canonical `energy_source` keys; strict sjoin for offshore wind (1 coastal-gap unit region-null → bad); no pytest.

Two-axis review: **Standards** (conformance + smells) and **Spec** (faithful implementation), deliberately kept separate.

---

## Standards

- **Hard — leftover `syn_` literal despite the claimed single-source remediation.** The prior review recorded the standard: "`SYNTHETIC_ID_PREFIX` now lives in `etl/config.py`… imported by both transform and verify." Both sub-agents independently caught that `etl/transform.py:97` still counts synthetic identities with the raw literal `df["unit_id"].str.startswith("syn_")`, and `etl/transform.py:182` re-documents the prefix in prose. Renaming the config constant silently skews the synthetic-count report line plus the verify gate that cross-checks it — exactly the drift the remediation claimed to close. `verify.py` derives its LIKE pattern from the constant; the transform count does not. The two only stay consistent by coincidence (though the cross-check makes the breakage fail loudly). *Fix: `df["unit_id"].str.startswith(SYNTHETIC_ID_PREFIX)`.*
- **Primitive Obsession / Data Clumps — storage shape (`db_utils.py:37-44`).** The two-column shape is an f-string fragment addressed by tuple index (`STORAGE_COLUMNS[0]` → `TEXT`, `[1]` → `DOUBLE PRECISION`); the column names travel in the tuple while their types live only in the DDL string. Swapping the tuple order silently attaches the types to the wrong columns. A `{column: type}` mapping would bind names to types. Judgement call — a 2-column delta keeps this low-severity.
- **Duplicated Code — storage column names recur as literals (`verify.py:200,208`).** `STORAGE_COLUMNS` covers the schema-existence check but is bypassed for the data-level checks (`storage_type IS NULL`, `storage_capacity IS NOT NULL`); the whitespace-aligned DDL also re-encodes both names. The "storage shape" concept lives across `db_utils.py`, `verify.py`, and `STAGING_COLUMNS` in `transform.py` with no single home. Judgement call.
- **Repeated Switches — `source == "storage"` (`db_utils.py:39`, `verify.py:185`).** Two sites, genuinely different concerns (DDL vs verification); consistent with the prior review's pass. Judgement call, no action.
- **Data Clumps (config/db_utils) — reinforced, not new.** `STORAGE_COLUMNS` in infra modules joins `BAD_QUALITY_PROPERTY`; the domain-module suggestion from the prior review still stands. Judgement call.
- **Speculative Generality — `SYNTHETIC_ID_EXPECTED={"solar": 39}` (`verify.py:22`).** Hard-coded per-source count that can drift on data refresh; defensible because the AC literally demands 39 and the repo's philosophy is "fail loudly on drift". Judgement call, keep.
- **Not flagged:** the capacity gate split (`installed_capacity is null` / `installed_capacity <= 0`) matches CONTEXT.md's Bad quality definition exactly; `SOURCE_NAMES` driving the CLI choice and the filename regex is a genuine single-source; `SYNTHETIC_ID_LIKE` deriving from the constant is correct; verify never string-matches reason strings, so the reason renames don't reopen prior Shotgun Surgery.

## Spec

Reviewed against issue #5 + issue #4 (blocker, "bad_quality rows must never be loaded into core") + TechnicalSpecification.md + CONTEXT.md + ADR 0001/0005.

- **(a) AC "zero unmapped units" is not literally met.** The strict `intersects` sjoin leaves offshore unit SEE982025668680 region-null (≈4 m coastal polygon gap), so verify reports it unmapped and the quality gate marks it `bad_quality`. Because #4 requires bad_quality rows to stay out of core, an in-EEZ turbine is silently dropped from the final dataset. This is the documented, user-accepted strict-sjoin interpretation — but the AC wording ("zero unmapped units within Germany's EEZ plus the onshore set") is technically unsatisfied for a unit inside the EEZ.
- **(b) Scope creep — `energy_source` retained on the storage staging table.** The spec's storage staging listing (TechnicalSpecification.md:169-186) omits the column; the implementation keeps it (DDL + STAGING_COLUMNS). Recorded as an accepted delta (raw carries it, marts pivot on it), but it widens the storage shape beyond the spec.
- **(b) Capacity gate split drifts the reason vocabulary.** Issue #4 phrased the check as the single "installed_capacity ≤0 or null" failure; splitting into two reason strings changes the stored `bad_quality` property-link values and the bad-quality distribution baseline. Deliberate (better diagnostics), but not asked for.
- **(c) Synthetic-prefix single-source is half-done** — same root cause as the standards hard finding (`transform.py:97` literal vs config constant). Self-protecting: a rename would surface as a verify count mismatch and fail loudly. Still, the documented remediation is incomplete.
- **(c) `storage_capacity` type vs spec — log a discrepancy, don't change.** TechnicalSpecification.md:174 lists `storage_capacity` as `str`; the DDL declares `DOUBLE PRECISION`. The spec is self-inconsistent (the raw layer's column is numeric), the implementation follows the data; per AGENTS.md, the data wins. Worth a logged discrepancy.

**AC cross-check:** three of four ACs fully implemented; storage shape and geo_accuracy=2 unflagging correct; outstanding risks are the non-literal "zero unmapped" (data-loss consequence) and the unrequested storage `energy_source` column — both knowingly accepted and documented.

---

## Summary

- **Standards — 6 findings** (1 hard — the leftover `syn_` literal at `transform.py:97` contradicting the claimed single-source remediation; 5 judgement calls/smells, most carried-forward). Worst: that hard literal.
- **Spec — 4 findings** (2 accepted deltas, 1 self-protecting partial, 1 log-worthy type discrepancy). Worst: the non-literal "zero unmapped" AC whose data-loss consequence is accepted but unsatisfied.