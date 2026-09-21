# Code review — data-driven + configurable pipeline inputs (issue #33)

- **Date:** 2026-09-21
- **Fixed point:** HEAD (`ca4967c`) — uncommitted working tree
- **Diff:** `git diff HEAD` + untracked `scripts/stamp_boundary_levels.py`,
  `tests/test_config.py`, `tests/test_extract.py`
- **Reviewed artifacts:** `etl/config.py` (accessors), `etl/utils.py` (anchored
  FILENAME_PATTERN + `_source_from_filename`), `etl/extract.py`
  (`extract_boundaries` level-from-data), `etl/__main__.py` (folder-driven
  `extract`, optional `boundaries`/`extract` targets, no-arg `run-all`),
  `etl/db_schema.py` (`BOUNDARY_FILE_LEVELS` deleted), `scripts/stamp_boundary_levels.py`
  (new), `scripts/seed_data_volume.sh`, `.env.example`, `README.md`,
  `docs/containerization.md`, `docs/remote-deploy.md`, `tests/test_config.py` (new),
  `tests/test_extract.py` (new)
- **Spec:** issue #33 (folder-driven extract with anchored regex + SOURCE_NAMES order,
  log-skip `Solar_Energy_Polygons`/`Cogeneration_Units`; boundary levels read from gpkg
  data with loud failure on missing `level`, `BOUNDARY_FILE_LEVELS` deleted,
  `BOUNDARY_LEVEL_COLUMNS` kept; repo-anchored read-at-call `sources_data_dir()` /
  `boundaries_manifest()` accessors; optional CLI targets defaulting from them, `run-all`
  no-args; `sources.txt` removed, seed/containerization de-referenced; `tests/test_config.py`;
  `.env.example` + README docs)

## Standards

**No hard violations.** The implementation follows the repo conventions: issue-scoped
docstrings and #33-referenced comments; anchored regex and casefold mapping match the issue
verbatim; pytest-only tests; `BOUNDARY_LEVEL_COLUMNS` untouched for #32 (sequencing
respected); read-at-call env accessors matching the `load_dotenv` repo-root-anchoring
precedent. Findings are judgement calls:

- **Spec drift, unflagged** — `TechnicalSpecification.md` §1.1 documents a manifest-text-file
  input for extract; the diff replaces it with folder globbing and the spec is not annotated.
  AGENTS.md ("note the discrepancy rather than silently assuming") applies, but the change is
  #33-mandated and is documented in docstrings, README, `.env.example`, and tests. → not fixed
  (spec edits would be scope creep beyond the issue); flagged for a follow-up note if desired.
- **Duplicated Code — config accessors** repeated the `Path(__file__).resolve().parent.parent`
  anchoring shape. → fixed: single `REPO_ROOT` constant in `etl/config.py`, reused by
  `load_dotenv` and both accessors.
- **Circuitous reverse-scan** in `_source_from_filename` (casefold `for`-loop over the prefix
  map when the anchored regex already guarantees membership). → fixed: casefolded
  `_FILENAME_BY_UPPER_PREFIX` reverse map, one indexed lookup.
- **Silent last-wins on duplicate source stems** in the extract folder glob (behavioural
  change vs the manifest list). → fixed: warning log naming the kept and ignored file.

## Spec

**No missing requirements.** All acceptance points verified present: repo-anchored read-at-call
accessors; optional `extract`/`boundaries` targets defaulting from them with explicit args
winning; `run-all` invoking both with no args; anchored
`^(Bioenergy|Energy_Storage|Gas_Producer|Hydropower|Solar_Energy|Wind_Energy)_V\d{8}\.gpkg$`
(case-insensitive); SOURCE_NAMES-order processing; `Solar_Energy_Polygons`/`Cogeneration_Units`/
unknowns log-skipped; `level` read from the gpkg frame with a loud failure on a missing column;
`BOUNDARY_FILE_LEVELS` deleted while `BOUNDARY_LEVEL_COLUMNS` kept; `sources.txt` gone from
disk (deletion not representable in git — `data/` is gitignored); seed script and
containerization/deploy docs no longer reference it; `tests/test_config.py` green;
`.env.example` + README document both vars and no-arg usage.

- **Scope creep (benign):** the "must carry a single 'level' value" guard (consistent with the
  issue's "no silent mislabeling" motivation); `tests/test_extract.py` beyond the mandated
  `test_config.py` (both pre-agreed seams); `docs/remote-deploy.md` updated though outside the
  spec's doc list (it referenced `sources.txt`, so the removal was necessary).
- **Integration seam note:** the missing-level test routes through `extract_boundaries`, which
  requires a dev DB (as the whole suite does, per AGENTS.md); it is not a no-DB unit seam — the
  docstring already says the extraction runs against the database.

## Summary

- Standards: ~4 findings, all judgement calls; fixed 3 (config duplication, reverse-scan,
  duplicate-stem warning), 1 flagged (spec text drift).
- Spec: nothing missing; 3 benign scope-creep items, none warranting rework.
- Worst per axis: (Standards) un-annotated spec drift on the extract-input contract;
  (Spec) nothing actionable.