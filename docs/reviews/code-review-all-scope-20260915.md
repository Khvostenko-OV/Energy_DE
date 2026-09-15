# Code review — All scope (initial commit → HEAD)

- **Date:** 2026-09-15
- **Fixed point:** `842003e` (initial commit) — full-repo review
- **Diff:** `git diff 842003e...HEAD` — 50 files, 7244 insertions, 83 deletions
- **Commits:** 87 (`git log 842003e..HEAD --oneline`)
- **Reviewed artifacts:** complete ETL pipeline `etl/` (extract, transform, load, marts, verify, reports, utils, db_utils, db_schema, config, `__main__.py`), `tests/` (7 modules), `docs/` (ADRs, agents, reviews, CONTEXT) + AGENTS.md, README, TechnicalSpecification.md, requirements, opencode.json
- **Spec source:** TechnicalSpecification.md (v2.3.1), GitHub issues #2/#3/#6/#7/#8/#9, ADRs 0001–0006, CONTEXT.md
- **Standards sources:** AGENTS.md + CONTEXT.md + ADRs + TechnicalSpecification.md + existing etl/*.py conventions + docs/reviews/ house style + Fowler smell baseline (Refactoring ch.3)

Two-axis review: **Standards** (conformance + smells) and **Spec** (faithful implementation), deliberately kept separate.

---

## Standards

### Hard violations (documented standards)

1. **`service.boundaries` / `service.loaded_files` contradict every documented standard.** The spec puts `boundaries` in the Raw layer (TechnicalSpecification.md:113,155–162); CONTEXT.md:60 defines "the single level-coded `raw.boundaries` table"; ADR 0004:5 ("single non-versioned `raw.boundaries` table"); README.md:37. Code writes them to `SERVICE_SCHEMA` (extract.py:233, `_create_log_table` db_utils.py:41) — an undocumented `service` schema. The move commit (506c62c) never updated the docs; the reviewer convention "note the discrepancy rather than silently assuming" (AGENTS.md:29) was violated. Either the code or all five docs must change.
2. **Doc staleness.** AGENTS.md:4 still says "no application code… exists yet" and README.md:9 "The pipeline is not implemented yet" — both false after 7,244 insertions. AGENTS.md:17 claims "8 sources (incl. Solar polygons, cogeneration)" vs README.md:27 "6 sources" and `SOURCE_NAMES` (config.py:9) = 6. AGENTS.md:33 says storages "will get `storage_properties`… when they land"; they landed (ADR 0006 fully implemented).

### Baseline smells (judgement calls)

- **Duplicated Code (worst) — synthetic identity triplicated.** Same `"|".join(str(v)…)+sha256` shape in transform.py:263–266, load.py:371–377, and inline again in load.py:395–405 (20 lines apart). `_synthetic_hash`'s comment confesses it: "The inputs mirror the staging derivation so the hash is stable." → one home in utils.
- **Duplicated Code — per-kind DDL clones.** `_create_core_storages` (db_utils.py:119) vs `_create_core_generators` (:199) are ~80-line table-name-swapped clones; staging DDL (:71–116) restates the column list db_schema.py already owns as `STAGING_COLUMNS`, breaking its "Single home for the tables" claim.
- **Duplicated Code — verify clones.** `_verify_load_generators` (:294) / `_verify_load_storages` (:512) near-identical; precedent reviews sanctioned this as "stage-owns-its-verify" — noting it persists per convention.
- **Duplicated Code — test harness quadrupled.** `_drop_core`/`_loaded_core`/`_staging_ready` cloned in test_load_generators/storages, test_marts:42–76, test_core_dimensions despite conftest.py existing.
- **Dead Code + Middle Man.** `_is_fresher` (load.py:469) never called — freshness logic is inlined in `_partition_staging`. `verify_marts` (marts.py:144) is a pure pass-through used only by tests.
- **Mysterious Name.** `transform_sorces` (transform.py:38) — typo-frozen public API used across __main__, conftest, tests.
- **Data Clump.** Load signature `(filename, filesize, modified_at)` floats as a bare tuple (extract.py:65, utils.py:58) though CONTEXT.md:84 names it a domain concept.
- **Repeated Switches.** `source == "storage"` recurs (db_utils.py:57, verify.py:169); collision detectors `_detect_region_null`/`_detect_onshore_in_sea`/`_detect_storage_capacity` (load.py:660–746) are one shape differing only by WHERE.

**Not flagged:** f-string SQL via schema constants, report/try-except/`summary()` shape, `_`-prefixed helpers — all match existing conventions.

---

## Spec

### (a) Missing / partial

1. **Spec's raw layer tables were relocated off-spec.** Spec section "1. Raw" defines `loaded_files` ("list of datafiles loaded into Raw layer") and `boundaries` as raw-layer tables; ADR 0004 states "Boundary files land in a single non-versioned `raw.boundaries` table" and CONTEXT.md still calls it `raw.boundaries`. The code instead writes `service.boundaries` (extract.py:232) and `service.loaded_files` (db_utils.py:41, utils.py:64/80) in a `service` schema that exists nowhere in the spec. The spec's four-layer structure (raw/staging/core/marts) gains an undocumented fifth schema, and ADR 0004/CONTEXT were never updated to match.
2. **ADR 0004's "load-if-not-exists" boundary guard is not implemented.** `extract_boundaries` always writes the first file with `if_exists="replace"` (extract.py:232–236), so any re-run of `python -m etl boundaries` wipes the reference table. ADR 0004 mandates load-if-not-exists. Previously flagged in code-review-extract-v2-20260912.md:31 and still open.

### (b) Not asked for

- The `service` schema itself (see a1) is scope creep relative to the spec's data layers. The `run_all` orchestration, idempotency self-check, and targeted incremental-collision optimization are additive but consistent with the issues' verification demands — not flagged.

### (c) Implemented but wrong

1. **`close_to` is not a property link.** Spec Load check: "add property 'collision' with collisions description, add property 'close_to' with reference to close unit" (TechSpec line 77). ADR 0005 binds: "write descriptive property links (`collision`, and `close_to` naming the neighbouring unit's id)"; issues #6/#7 acceptance criteria require "`collision` / `close_to` links". Instead close neighbours are written as a `close_to` JSON list inside the core `secondary_attributes` column (load.py:812–838 `_write_close_locations`; comment at load.py:586), and `_reset_collision_annotation` actively *deletes* `close_to` property links as "Deprecated" (load.py:884–904). No `close_to` property link is ever produced — the spec's "add property 'close_to'" is unmet; CONTEXT.md's "Close-to: The property link value" is now false.
2. **Gas capacity semantics (resolved by ADR).** Issue #3 asked that `gas_production_capacity` be "preserved… without pretending to be installed capacity," but extract maps it into `installed_capacity` (extract.py:81, db_schema.py:38). ADR 0002 explicitly sanctions this — binding, so not a violation, merely noting the issue criterion is unmet by design.

**Verified correct:** six-source manifest coverage (Cogeneration/Solar Polygons correctly excluded per "not using for now"), versioned raw names, 14-key whitelist decomposition, per-kind core property tables (ADR 0006), serial core identity with freshness gate, and the three materialized-view marts with `outside` bucket (marts.py:49–94).

---

## Summary

- **Standards:** 2 hard violations (off-doc `service` schema, stale docs) + 8 smell clusters; worst is the synthetic-identity hash triplicated across transform/load, with the `service`-vs-docs contradiction as the only hard breach needing a side decision.
- **Spec:** 2 missing/partial + 1 scope-creep + 2 implemented-but-wrong (1 binding-resolved); worst is `close_to` required as a property link (spec + ADR 0005 + issues #6/#7) but implemented as a JSON `secondary_attributes` value and actively deleted by `_reset_collision_annotation`.