# Code review — boundary GeoJSON prep (#17)

- **Date:** 2026-09-16
- **Fixed point:** `HEAD` (d08be47) — review of the uncommitted working tree (the work was committed after review)
- **Diff:** `git diff HEAD` + new untracked files (`etl/viz_prep.py`, `tests/test_viz_prep.py`)
- **Spec source:** GitHub issue #17 (fetched via `gh issue view 17`)
- **Recommended reviewers:** codebase-design
- **Reviewed artifacts:** new `boundaries-geojson` ETL CLI subcommand, `etl/viz_prep.py` (GeoPandas read → Douglas-Peucker simplify → 6-decimal rounding → per-level GeoJSON), `_verify_viz_prep` in `verify.py`, `VizPrepReport` in `reports.py`, unit + integration tests in `tests/test_viz_prep.py`

## Standards

Two parallel-review findings:

1. **Duplicated Code — level-count query written a third time.** `_verify_viz_prep` copied the `SELECT level, COUNT(*) ... GROUP BY level` shape already present in `_verify_boundaries` (the two sat ~30 lines apart in `verify.py`), and `generate_boundaries_geojson` re-encoded boundary reads again. **Fixed:** extracted `_boundary_level_counts(engine)` in `verify.py`; both `_verify_*` functions now share it.

2. **Speculative Generality — tunable simplify params.** `_simplify_geometry(geometry, tolerance=..., decimals=...)` carried two defaulted parameters no caller or test ever overrides. **Fixed:** dropped the parameters, kept the module constants (`SIMPLIFY_TOLERANCE`, `ROUND_DECIMALS`) in the body.

3. **Divergent Change (judgement call, accepted).** `BOUNDARY_GEOJSON_FILES` (level → GeoJSON filename) landed in `db_schema.py`, whose docstring declares it the DB-schema home. Kept deliberately: the module already owns the sibling `BOUNDARY_FILE_LEVELS` (filename → level) and `BOUNDARY_LEVEL_COLUMNS` boundary mappings, so a level→filename mirror is within its documented scope, and placing it in `viz_prep.py` would force a lazy import to avoid the `viz_prep → verify` cycle.

4. **Spec-vs-stack note (no violation, recorded).** The diff's docstrings name a "Dash app's choropleth layer" while AGENTS.md/README document Metabase as the dashboard stack. Per the "note the discrepancy rather than silently assuming" convention, commented on issue #17; the GeoJSON assets are stack-agnostic (static files) and the consuming app work is tracked separately (#18/#19).

## Spec

All five acceptance criteria satisfied:

| AC | Result |
|----|--------|
| CLI subcommand `boundaries-geojson`, per-level file mapping, `boundaries`/`extract` pattern, `get_engine` reuse | ✅ `__main__.py` `boundaries_geojson` command; `BOUNDARY_GEOJSON_FILES` in `db_schema.py`; reuses `generate_*` → `get_engine()` path and the report + `SystemExit(1)` shape |
| Valid GeoJSON, one Feature per boundary row, simplified geometry, ~6-decimal precision | ✅ `generate_boundaries_geojson` → `_simplify_geometry` (Douglas-Peucker `preserve_topology`, `round(…, 6)`); per-file feature counts verified live |
| `_verify_viz_prep` runs after generation, returns `list[str]` (empty = pass), checks per-level counts vs `service.boundaries` | ✅ `verify.py:_verify_viz_prep` |
| Integration test against live DB: level coverage + geometry validity | ✅ `tests/test_viz_prep.py` (`test_feature_counts_match_service_boundaries`, `test_generated_geometries_are_valid`) |
| Unit test on synthetic polygons: valid geometry, bounded file size | ✅ `test_simplify_reduces_vertex_count`, `test_simplified_geojson_file_size_is_bounded` (+ rounding / multipolygon / shape-preservation cases) |

Review findings triaged:

- **Validity claim overstated (fixed).** `_simplify_geometry`'s docstring implied `preserve_topology=True` alone keeps a valid input valid, but the coordinate-rounding step runs outside topology preservation and can collapse sub-centimetre segments into slivers. `preserve_topology` covers only the simplify step; fixed by adding a `make_valid` repair when rounding produces an invalid result (and the docstring now says exactly that).
- **Test fixture docstring mislabelled (fixed).** `_staging_ready` claimed staging's transform session also *loads* boundaries; it doesn't — transform merely *requires* them (conftest fails cleanly if missing). Docstring corrected.
- **Asset-dir shipping deferred (noted, not built).** "What to build" says the files are "shipped in the image's asset directory", but no AC requires it and the consuming Dash app (#18) does not exist yet. Shipping the assets into the image belongs with the app work; captured in the issue comment.

```text
Summary: Standards — 4 findings (2 fixed, 1 accepted judgement call, 1 recorded note), worst fixed. Spec — all 5 ACs met; 2 findings (1 doc fix, 1 deferred-by-design).
```