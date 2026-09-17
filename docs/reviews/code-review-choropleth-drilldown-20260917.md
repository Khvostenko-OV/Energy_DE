# Code review — choropleth drill-down (#19)

- **Date:** 2026-09-17
- **Fixed point:** `980a4ee` (pre-#19, the #18 HEAD) — review of `git diff 980a4ee...HEAD`
- **Diff:** `git diff 980a4ee...HEAD` (7 commits: 9607954, 602f090, c1d4dde, c3b2e4f, 7b41919, 7778a4d, b91e424)
- **Spec source:** GitHub issue #19 (fetched via `gh issue view 19`)
- **Reviewed artifacts:** `viz/drill.py` (plan_drill / drill_value / DrillFilter / DrillValue), `viz/data.py` (fetch_level_fills, load_level_geojson, VIZ_BOUNDARY_ASSET_DIR), `viz/figure.py` (add_choropleth_fill, centroids_by_name, DRILL_ZOOMS), `viz/palette.py` (CHOROPLETH_COLORSCALE), `viz/app.py` (next_drill_state, drill_on_click / render_units_map callbacks), and the unit + integration tests (`tests/test_viz_drill/choropleth/app/assets/data.py`)

## Standards

1. **Speculative Generality / Dead Code — `DrillFilter.parent_chain` (fixed).** The field, its `__post_init__` freeze, and its `field(default=...)` machinery were stored but nothing read them — `next_drill_state` re-derived the chain from `state["parent_filters"]`. **Fixed:** dropped the field; `plan_drill` builds `parent_filters` directly.
2. **Mysterious parameter — `metric` on `plan_drill` (fixed).** Used only for a validation `if metric not in VALUE_EXPRESSIONS`, duplicating the check already inside `drill_value` (the actual consumer). Threading it through implied the filter depended on the metric. **Fixed:** removed the param; `drill_value` is the sole metric validator; the filter is metric-agnostic by construction, enforced by signature + the `test_metric_never_enters_the_filter_build` key-set assertion.
3. **Duplicated Code — query shape written twice (accepted).** `fetch_level_fills` and the `_direct_fills` test oracle repeat the active-union + GROUP BY shape, and `/1000.0` appears in both `VALUE_EXPRESSIONS` and test strings. The oracle mirrors the seam *on purpose* (reconcile test); documented divergence, not a violation.
4. **Security note — SQL injection (fixed).** `fetch_level_fills` built `f"{name} = '{area}'"` with browser-clicked values; `area` is user-supplied. **Fixed:** area values are now SQLAlchemy bound parameters, and filter column names are whitelisted against `BOUNDARY_LEVEL_COLUMNS.values()` (raises `ValueError` before any DB access); pinned by `test_foreign_filter_column_is_rejected_before_db_access`.
5. **Annotation — `_feature_centroid` (fixed).** Declared `-> tuple[float, float]` but returns `None` for empty geometry. **Fixed:** `-> tuple[float, float] | None`.

No hard violations vs. AGENTS.md (filenames-over-spec, per-unit-kind properties, service schema). `fetch_level_fills` re-aggregates `core` directly rather than via the marts — the spec itself demands "computed live from `core` ... never from the marts", so the spec overrides the marts read path.

## Spec

All five acceptance criteria satisfied (after fixes).

| AC | Result |
|----|--------|
| Choropleth layer renders the active drill level from asset GeoJSON beneath scatter, colored by MW sum (default) or unit count (toggle) | ✅ `add_choropleth_fill` inserts a `go.Choroplethmap` at trace index 0 (via the permutation trick), `load_level_geojson` reads `level_{1,2,3}.geojson` through `VIZ_BOUNDARY_ASSET_DIR`; DRILL_ZOOMS has a real 1→2→3 progression |
| Clicking a fill drills 1 → 2 → 3, zooming to the selected area's children; no drill past level 3 | ✅ `plan_drill` returns `None` at level 3 → `next_drill_state` resets to overview; **zoom fixed** (was center-only) — `_build_map` now sets `layout.map.zoom` per level |
| Live aggregate returns correct (area name, metric) values at each level, reconciles with direct SQL | ✅ `fetch_level_fills` groups the active generator+storage union by `COALESCE(level_column, out-of-region)`, honoring the parent chain |
| Unit test: drill callback maps a clicked area to the correct child-level query for both metrics | ✅ `tests/test_viz_app.py::TestDrillState` (6 tests) drives `next_drill_state` through 1→2→3 with both metrics, asserting level, parent chain, and metric preservation; `tests/test_viz_drill.py` pins the metric-free filter |
| Integration test: fill values for regions/districts/municipalities reconcile against a direct `core` GROUP BY over the live DB | ✅ `tests/test_viz_data.py::TestLevelFills` compares the full name→value map (tolerance `1e-6`) to a hand-written `core` GROUP BY at levels 1–3, both metrics |

Findings triaged:

- **AC2 "zoom to the selected area's children" (fixed).** `_build_map` previously set only `layout.map.center` while `build_units_map` fixed `zoom=INITIAL_ZOOM` (5.5, country scale), so a drill click re-centered but never zoomed. **Fixed:** `DRILL_ZOOMS = {1: 5.5, 2: 6.5, 3: 8.5}` in `viz/figure.py`, applied in `_build_map`.
- **Centroid source (correct, verified).** `next_drill_state` looks up the clicked area's centroid in the *current* level's GeoJSON — correct, since the clicked name is a feature of the current level, not the target level's children.
- **Scope beyond ACs (accepted).** `DrillFilter`/`DrillValue` immutability, the `VIZ_BOUNDARY_ASSET_DIR` env seam (shared with #21), and the `outside` area bucket for null keys (mirrors the marts convention; that row has matching geo, so it renders visibly only in the reconcile test) are reasonable implementation details, not creep.
- **`metric` validation moved (accepted).** Previously `plan_drill` raised on unknown metrics; after removing the param, unknown metrics are still rejected at the value seam (`drill_value`) and at the figure seam (`add_choropleth_fill`), so the failure surface is unchanged.

Summary line:

```text
Summary: Standards — 5 findings (4 fixed, 1 accepted duplication), worst fixed dead DrillFilter.parent_chain; Spec — all 5 ACs met, 2 fixes applied (AC2 zoom, SQL bound params), remainder accepted.
```

**Fixes applied in commit `b91e424`:** drop dead `parent_chain` field; drop redundant `metric` param from `plan_drill`; bind parent-filter area values as SQL params + whitelist filter column names; add per-level drill zoom; fix `_feature_centroid` annotation. Full suite green afterward: **205 passed**.