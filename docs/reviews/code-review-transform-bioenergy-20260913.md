# Code review — Transform bioenergy end-to-end (issue #4) + refactor commits

- **Date:** 2026-09-13
- **Fixed point:** `03affe5` (parent of the first transform commit, `94579a8`)
- **Diff:** `git diff 03affe5...HEAD` — 4 commits, 852 insertions / 276 deletions
- **Reviewed artifacts:** `etl/transform.py`, `etl/reports.py`, `etl/verify.py`, `etl/db_utils.py`, `etl/utils.py`, `etl/extract.py`, `etl/config.py`, `etl/__main__.py` (`opencode.json` permission edit excluded)
- **Spec source:** GitHub issue #4 (Transform — Bioenergy end-to-end) + TechnicalSpecification.md + CONTEXT.md + ADR 0001/0004/0005
- **Standards sources:** AGENTS.md + CONTEXT.md + ADRs + Fowler smell baseline (Refactoring ch.3)

Two-axis review: **Standards** (conformance to documented standards + smells) and **Spec** (faithful implementation of issue #4), deliberately kept separate.

---

## Standards

- **Hard (documented standard):** `verify.py:_verify_boundaries` queries `{SERVICE_SCHEMA}.boundaries` (`serv`), but ADR 0004 and CONTEXT.md both say boundaries live in a single non-versioned `raw.boundaries` table. This predates the diff (carried from `utils.py`), but the new `verify.py` inherits it. *(Context: the code comments in `transform.py` record the drift — extract v2 moved boundaries to `serv` in 506c62c, which lands before this review range; ADR 0004/CONTEXT.md appear stale rather than the code being wrong.)*
- **Duplicated Code:** `reports.py` — all three report classes (`BoundariesReport`, `ExtractionReport`, `TransformReport`) declare `errors: list[str]`, a `passed` property returning `not self.errors`, and a `summary()` that iterates `self.errors` identically. A shared error-handling base/mixin would remove the repetition.
- **Divergent Change:** `utils.py` is still a grab-bag — versioning helpers, log helpers, filename parsing, dedup, boundary-area computation all live side by side, each edited for a different reason. The split into `reports.py`/`verify.py`/`db_utils.py` is good but incomplete; versioning and boundary-area helpers could move closer to their consumers.
- **Data Clumps (config):** `BAD_QUALITY_PROPERTY = "bad_quality"` sits in `config.py` next to schema names and `get_engine()`. Schemas/engine are infrastructure; the property name is a domain constant used by `transform.py`, `db_utils.py`, and `verify.py`. Consider a domain-oriented home (`transform.py` or a `domain.py`).
- **Shotgun Surgery (minor):** the quality reason strings (`QUALITY_CAPACITY`/`DATES`/`COORDS`/`REGION`) live only in `transform.py`, while `verify.py` reconstructs the `bad_quality` property link by string-matching `BAD_QUALITY_PROPERTY` against stored values. A reason-string change would silently mismatch verify.

## Spec

Reviewed against issue #4, TechnicalSpecification.md, CONTEXT.md, ADR 0001/0005.

- **(a) Partial / accepted delta — `secondary_attributes` not preserved in staging.** Issue #4: *"build the staging row: … `secondary_attributes` preserved."* The staging DDL (`db_utils.py`) has no `secondary_attributes` column. Accepted in a prior review as redundant post-decomposition (attributes live in `properties`/`units_properties`), but it is a spec delta and deserves an explicit ADR/issue note rather than living silently in code.
- **(b) Scope creep — module decomposition beyond the ticket.** Issue #4 is scoped to *"transform — bio end-to-end."* The range also extracts `ExtractionReport`/`BoundariesReport` → `reports.py`, `_verify_extraction`/`_verify_boundaries` → `verify.py`, `_ensure_schema`/`_create_log_table`/`_create_staging_tables` → `db_utils.py`, and moves `RAW_COLUMNS`/`RAW_COLUMN_MAPPING`/`BOUNDARY_*` into `extract.py`. Reasonable structural refactors, but they belong to 2 of the 4 commits in the range and were not part of the issue's build list.
- **(c) Potentially wrong — natural-key uniqueness check omits synthetic IDs.** Issue #4 AC: *"natural-key uniqueness … fail loudly on drift."* ADR 0001: rows without a `reference_id` get a synthetic hash, staging-only. `verify.py` checks uniqueness on `(energy_source, reference_id) WHERE reference_id IS NOT NULL` — `syn_*` rows are excluded, so a synthetic-hash collision would go undetected at verification time. Dormant today (bio has no synthetic IDs), but the `unit_id` PK contract is not fully verified for sources that do.

**AC cross-check:** staging shape ✓ (minus `secondary_attributes`, accepted delta); spatial joins region/district/municipality ✓ with coverage report ✓; `bad_quality` property link with `\n`-joined reasons ✓, passing rows unflagged ✓; decomposition into `properties`/`units_properties` with counts asserted ✓; verification: natural-key ✓ (gap: synthetic IDs), join coverage ✓, decomposition counts ✓, bad-quality distribution ✓ — all fail loudly on drift ✓.

**Primary defect:** the natural-key verification only covers non-null `reference_id` rows, leaving synthetic identities unverified (dormant for bio).

---

## Summary

- **Standards — 5 findings** (1 hard flag, since contextualised as stale ADR/CONTEXT on `serv` vs `raw` boundaries; 4 judgement-call smells); worst: `raw` vs `serv` boundaries discrepancy between code and ADR 0004/CONTEXT.md.
- **Spec — 3 findings** (1 accepted delta, 1 scope creep, 1 potentially wrong); worst: synthetic `syn_*` unit IDs are excluded from the natural-key uniqueness verification.