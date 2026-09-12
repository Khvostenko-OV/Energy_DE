# Code review — Extract v2 (all changes vs pre-ETL baseline)

- **Date:** 2026-09-12
- **Fixed point:** `9e61019` (parent of the first ETL commit, `e4d6ac8`)
- **Diff:** `git diff 9e61019...HEAD` — 23 commits, 858 insertions
- **Reviewed artifacts:** `etl/extract.py`, `etl/utils.py`, `etl/config.py`, `etl/__main__.py`, `requirements.txt`
- **Spec source:** GitHub issue #10 (extract v2) + TechnicalSpecification.md + CONTEXT.md
- **Standards sources:** AGENTS.md + CONTEXT.md + Fowler smell baseline (Refactoring ch.3)

Two-axis review: **Standards** (conformance to documented standards + smells) and **Spec** (faithful implementation of issue #10), deliberately kept separate.

---

## Standards

Reviewed `etl/extract.py`, `etl/utils.py`, `etl/config.py`, `etl/__main__.py` against AGENTS.md + CONTEXT.md and the smell baseline.

- **Hard (documented standard):** `secondary_attributes` is TEXT, not jsonb. CONTEXT.md:84/:100 and TechnicalSpecification.md:121/:138 prescribe a jsonb column; the code writes stringified JSON text (`json.dumps(d, default=str)`, utils.py:246–248, commit `17af9ce`). AGENTS.md requires discrepancies be *noted*; no ADR records this drift. Implementation no longer matches the authoritative docs without a decision record.
- **Duplicated Code:** the manifest-parsing loop (`line.strip() for line in manifest.read_text().splitlines() if ... startswith("#")`) appears twice — `etl/__main__.py:36–40` and `etl/extract.py:42–46` — and the `if not manifest.is_file(): raise click.BadParameter(...)` guard also twice (`__main__.py:29–31`, `:79–81`).
- **Primitive Obsession + Data Clumps:** the Load Signature is a *named domain concept* in CONTEXT.md:80, but the code carries it as an anonymous tuple into `_is_logged` and then re-spells the three fields as separate params in `_log_load(engine, filename, filesize, modified_at, loaded_to)`. The type wants to be born.
- **Mysterious Name:** `t0`…`t7` perf-timer locals scaffold `extract_source` (`etl/extract.py:47–84`) — eight inscrutable tick names where elapsed spans would do.
- **Speculative Generality:** `engine: Engine | None = None` + `engine or get_engine()` on every public entry point while the only caller always passes the default.
- **Inconsistent twins:** `RAW_COLUMNS` is a `list` (utils.py:19), `BOUNDARY_RAW_COLUMNS` a `tuple` (utils.py:46) — same concept, no reason for different containers.

Borderline-noted: `get_engine()` thin wrapper, and the shared `passed`/`summary`/`errors` shape on the two report dataclasses are small enough to leave.

## Spec

Reviewed against issue #10 (extract v2), TechnicalSpecification.md, and CONTEXT.md.

- **(a) Missing — boundaries "if it does not exist" is not implemented.** Spec: boundary files "load into raw.boundaries **if it does not exist**". `extract_boundaries` never checks existence — the first file writes with `if_exists="replace"` (extract.py:192–196), so any re-run (`run_all`) wipes the reference table. `BoundariesReport.summary` even advertises "already present" (utils.py:98) yet no such path exists.
- **(a) Partial — the `properties`→`secondary_attributes` rename is absent as a rename.** `COLUMN_MAPPING` only maps `gas_production_capacity` (utils.py:33–35). The output column is built by construction in `_build_secondary_attributes`; a column genuinely named `properties` in a source would be folded *inside* the JSON dict, never surfaced as the top-level column.
- **(b) Scope creep — `run_all` and the `boundaries` CLI subcommand** add orchestration/UX the issue never requested (its build list covers manifest, versioned loads, loaded_files, force, boundaries — no run sequencing).
- **(c) Potentially wrong — storage columns are loose.** `storage_type` is a raw column (utils.py:30) with no mapping and no cast; if the storage file names it differently it silently disappears (and `storage_capacity` becomes NULL). AC6 can't be confirmed from code alone.

**AC cross-check:** 1 ✓ versioned naming, `_2` on same-day reload; 2 ✓ skip leaves `loaded_files` untouched; 3 ✓ `-f` → new version + distinct `loaded_to` row; 4 ✓ append-only INSERT, all five fields, no unique constraint; 5 ✗ levels/one-level-0/km² only verified on this run — re-run replaces instead of "if it does not exist"; 6 ⚠️ column named `secondary_attributes`, null-`reference_id` rows kept, `reference_date` is a timestamp — but the literal rename is missing; 7 ✓ count + unique non-null `reference_id` verification.

**Primary defect:** the boundaries "if not exists" guard (extract.py:192–196).

---

## Summary

- **Standards — 6 findings** (1 hard + 5 judgement calls); worst: jsonb→text column drift with no ADR note.
- **Spec — 4 findings** (2 missing/partial, 1 scope creep, 1 potentially wrong); worst: `raw.boundaries` replaced on every run instead of "if it does not exist".