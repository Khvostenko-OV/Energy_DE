# Code review — Transform all sources incl. offshore + synthetic identity (issue #5)

- **Date:** 2026-09-13
- **Fixed point:** `HEAD` (`ae67c33`) — reviewed the uncommitted working-tree diff
- **Diff:** `git diff HEAD` — 6 files, 94 insertions / 11 deletions (`etl/transform.py`, `etl/verify.py`, `etl/db_utils.py`, `etl/config.py`, `etl/reports.py`, `etl/__main__.py`)
- **Reviewed artifacts:** the transform stage scaled from bio-only to all six sources: storage-aware staging DDL, per-source staging columns, synthetic-identity verification, storage-shape verification, CLI choices + `run_all` transforms
- **Spec source:** GitHub issue #5 + TechnicalSpecification.md + CONTEXT.md + ADR 0001/0005 + prior review `code-review-transform-bioenergy-20260913.md`
- **Standards sources:** AGENTS.md + CONTEXT.md + ADRs + Fowler smell baseline (Refactoring ch.3)
- **Decisions locked with the user:** lowercase canonical `energy_source` keys (issue #4 convention); strict sjoin for offshore wind (1 unit at a ~4 m coastal polygon gap is region-null → bad, so "zero unmapped" is knowingly not literal); no pytest suite (verify via DB).

Two-axis review: **Standards** (conformance + smells) and **Spec** (faithful implementation), deliberately kept separate.

---

## Standards

- **(fixed) Synthetic-ID uniqueness gap from the prior review is closed.** `_verify_transform` now checks the stored synthetic count against the computed count, enforces synthetic `unit_id` uniqueness, and gates the per-source expectation (39 solar). The only dormant gap — synthetic rows excluded from natural-key uniqueness — is now explicitly verified.
- **Hard — `syn_` prefix duplicated across files.** `etl/transform.py:_synthetic_unit_id` embeds the raw `"syn_"` literal while `etl/verify.py` derives its LIKE pattern from a local `SYNTHETIC_ID_PREFIX`. Renaming the prefix in one place would silently break the other. *Remediated:* `SYNTHETIC_ID_PREFIX` now lives in `etl/config.py` next to `BAD_QUALITY_PROPERTY`, imported by both transform and verify.
- **Duplicated Code (reports.py) — unaddressed, pre-existing.** The shared `errors`/`passed`/`summary` shape across the three report classes was flagged last review; this diff only adds a field to the same structure. Left as out-of-scope refactor.
- **Data Clumps (config.py) — reinforced.** `STORAGE_COLUMNS` joins `BAD_QUALITY_PROPERTY` in the schema/infrastructure module. Both are domain constants in an infra home; the prior review's suggestion (domain module) stands but is a judgement call.
- **Shotgun Surgery (quality annotations) — pre-existing.** Reason strings still live only in `transform.py` while `verify.py` string-matches property names/values. The new synthetic-identity pair is no longer duplicated after remediation.

**Baseline smells (judgement calls):**
- **Primitive Obsession (`db_utils.py`):** the storage shape is an f-string fragment interpolated into `CREATE TABLE`; "storage ⇒ two extra columns" is a domain concept hiding behind string weaving. A small DDL builder or schema mapping would read better but is arguably over-engineering for a 2-column delta.
- **Repeated Switches:** `if source == "storage"` recurs in `db_utils.py`, `transform.py`, and `verify.py`. Each site does a genuinely different thing (DDL, column list, verification), so a shared mapping offered little and was not introduced.
- **Speculative Generality (`verify.py:SYNTHETIC_ID_EXPECTED={"solar": 39}`):** a hard-coded per-source count that could drift on data refresh. Kept deliberately: the AC literally requires 39 synthetic identities, and "fail loudly on drift" is the repo's stated verification philosophy.

## Spec

Reviewed against issue #5 (scaling transform to all six sources), TechnicalSpecification.md, CONTEXT.md, ADR 0001/0005.

- **(a) Missing/partial requirements — none material.** All six staging tables built with the bio mechanics; solar 39 synthetic identities present (`syn_` prefix, none dropped, 27 good / 12 bad-capacity); offshore wind = 1,688 sea-region rows (North Sea 1,380 + Baltic Sea 308) with the 1 coastal-gap unit region-null → bad; storage shape carried; geo_accuracy=2 (3,023 rows) unflagged; per-source verification all PASS.
- **(b) Scope creep — `energy_source` kept on the storage staging table.** The spec's storage staging listing (TechnicalSpecification.md:169-186) omits `energy_source`. It is retained deliberately: the raw storage table already carries it, CONTEXT.md's controlled vocabulary includes "Storage" as a canonical value, marts pivot on it, and dropping it would lose data vs raw. Recorded as an accepted delta, consistent end to end.
- **(c) Column-order divergence — fixed.** Storage DDL placed `energy_source` before the storage columns while `_staging_columns` yielded the reverse; name-based `to_postgis` worked but the layouts disagreed. `_staging_columns` now inserts the storage columns at index 2 (`unit_id, energy_source, storage_type, storage_capacity, …`), matching the DDL.
- **(d) Storage-shape verification strengthened** beyond column existence: `storage_type` must be non-null on every row, and the `storage_capacity` presence count is logged (1,250/1,348, matching the source). The AC is thus checked at the data level, not just the schema level.

**AC cross-check:** six staging tables ✓ uniform mechanics ✓; canonical labels enforced (lowercase source key convention from issue #4, user-confirmed) ✓; 39 solar synthetic identities, prefix-recognized, unflagged-in-v2 ✓; offshore wind joins level-1 sea regions (1,688) with 1 gap unit flagged ✓; storage shape carried + geo_accuracy=2 unflagged ✓; per-source verification (natural-key uniqueness incl. synthetics, join coverage, decomposition counts, bad-quality distribution) all PASS ✓.

---

## Summary

- **Standards — 5 findings** (1 hard — duplicated `syn_` prefix, remediated; 4 judgement calls / pre-existing); worst remaining: config.py continues to hold domain constants.
- **Spec — 4 findings** (1 accepted delta, 2 remediated, 1 strengthened); worst: none outstanding — `energy_source` on storage is a deliberate, recorded delta.