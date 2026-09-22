# Code review — viz perf: cache boundaries + materialize simplified geojson (issue #31)

- **Date:** 2026-09-22
- **Fixed point:** `b0e857b` (branch tip, `HEAD`) — uncommitted/staged work under review
- **Diff:** `git diff HEAD` — 10 files, 167 insertions, 38 deletions
- **Commits:** none (working tree, pre-commit)
- **Reviewed artifacts:** `etl/db_schema.py` (+`BOUNDARY_SIMPLIFY_TOLERANCE`), `etl/utils.py` (+`_refresh_boundary_geojson`), `etl/extract.py` (`extract_boundaries` + idempotent geojson backfill outside the skip path), `viz/data.py` (`boundaries_query` returns stored `name, area, geojson`, no `ST_Simplify`/`ST_AsGeoJSON`), `viz/choropleth.py` (+optional `pre_parsed_geometry`), `viz/app.py` (+`st.cache_data` wrappers keyed on `(level, str(engine.url))`, parsed-geometry threading, "Reload data" button); tests: `test_viz_data.py`/`test_viz_choropleth.py` updated/extended; docs: `TechnicalSpecification.md` + ADR 0007 updated for the `geojson` column
- **Spec source:** GitHub issue #31

## Standards

### Hard violations (documented standards)

None after fixes. Verified against the diff:

- **AGENTS.md "Conventions"** — ETL stages/ADR 0007 untouched in spirit; `service.boundaries.geojson` is a documented addition (spec table list + ADR 0007 now carry it, per the repo's "docs must catch up" convention used for the `service` schema drift).
- **etl/viz read-direction rule** — only `viz.data` imports `etl.db_schema`; the new ETL reconcile step never imports viz. Bound parameters everywhere (`:level`); the tolerance value is interpolated as a module constant, matching the existing `_compute_boundary_areas` shape.
- **CONTEXT.md / domain.md glossary** — names stay on-vocabulary; no new domain synonyms introduced.

Note: the full integration suite shows 2 pre-existing failures in `tests/test_load_storages.py::TestCollisions` (collision-link counts `close_phrase == close_units` → `250 == 249`). Reproduced identically on the clean tree (stash) — a pre-existing suite-ordering issue in the storage-load collision tests, unrelated to this change. Pass in isolation.

### Judgement calls (baseline smells)

**Middle Man / redundant token — `viz/app.py` cache wrappers.** `_cache_boundary_payload(engine_url, level)` accepts `engine_url` but never reads it in the body (it closes over the module-global `engine`); the string is a hash token for `st.cache_data`. This is the documented Streamlit idiom the issue itself requested ("keyed on `(level, str(engine.url))` — never hash the SQLAlchemy `Engine`"), so accepted; the comment now states the token role explicitly.

**Duplicated rationale prose.** The issue-#31 explanation is restated in `db_schema.py:88-92`, `utils.py` docstring, `extract.py:278-281`, `app.py:155-163` and `data.py:288-299`. Matches the codebase's deliberately verbose inline-rationale style (repo overrides — not flagged further), but the justification could drift if the tolerance ever changes.

**Broad-stroke UPDATE on every run.** `_refresh_boundary_geojson` re-simplifies all 458 rows on every `python -m etl boundaries` run, including the skipped one. The issue explicitly mandated this ("Must run outside the loaded_files early-return so existing DBs self-upgrade"), and measured ~1s on the seed DB — accepted as specced, noted for future tolerance bumps.

## Spec

Verified against issue #31. No missing requirements, no behaviour beyond the issue (the "Reload data" button is explicitly "optional" in the issue and implemented).

- **(a) Missing/partial** — none. All four acceptance criteria are addressed: tolerance moved to `etl/db_schema.py`; idempotent ALTER+UPDATE runs outside the skip path so existing DBs upgrade without `-f` (verified live: dropped the column on the seeded DB, re-ran `python -m etl boundaries`, column re-added and all 458 rows backfilled with valid JSON, no `-f`); `boundaries_query` returns `name, area, geojson` with no `ST_Simplify`/`ST_AsGeoJSON`; boundary rows + parsed geometries served from `st.cache_data` keyed on `(level, str(engine.url))`; `test_viz_data.py` updated for the new SQL (viz unit suite green with `requirements-viz.txt` only).
- **(b) Scope creep** — none material. `_cached_area_names` also caches the multiselect-options query (a `service.boundaries` query per rerun), which is required to meet "a rerun with unchanged level issues no boundaries DB query" — in-scope, not creep.
- **(c) Implemented wrong** — none. The cached tuple `(rows, geometries)` matches the issue's "parsed geometries ride along" wording; `pre_parsed_geometry` default keeps the `json.loads` path so `test_viz_choropleth.py` stays green; empty-dict pre-parsed falls back correctly.

Summary: Standards — 1 hard finding raised and fixed during review (an appended `0a` corruption from a sloppy newline fix; now resolved), plus 3 documented judgement calls, worst = the cache-key-token middle man (accepted idiom). Spec — 0 findings.

Reviewed per the code-review skill; report saved to `docs/reviews/code-review-viz-perf-boundary-geojson-20260922.md`.