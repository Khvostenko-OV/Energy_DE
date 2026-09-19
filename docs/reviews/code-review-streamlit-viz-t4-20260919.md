# Code review — Streamlit viz T4 levels/area selection/choropleth/viewport (issue #26)

- **Date:** 2026-09-19
- **Fixed point:** `426ec39` (current branch tip, `HEAD`) — uncommitted/staged work under review
- **Diff:** `git diff HEAD` plus untracked new files `viz/choropleth.py`, `viz/viewport.py`, `tests/test_viz_choropleth.py`, `tests/test_viz_viewport.py` — 11 files, 1010 insertions, 22 deletions
- **Commits:** none (working tree, pre-commit); the review led to fixes, then committed as `f61265d`
- **Reviewed artifacts:** `viz/choropleth.py` (new), `viz/viewport.py` (new), `viz/data.py` (+`boundary_names_query`/`fetch_area_names`, `boundaries_query`/`fetch_boundaries`, `boundary_fill_query`/`fetch_boundary_fill`, names-filtered `areas_query`/`area_name_query`/`fetch_areas`), `viz/app.py` (+area multiselect, choropleth fetch, camera session-state refit, header scope with names), `viz/map_builder.py` (+`build_choropleth_layer`), `viz/tooltip.py` (+`area_card`), tests: `test_viz_choropleth.py` (new), `test_viz_viewport.py` (new), `test_viz_data.py`/`test_viz_map_builder.py`/`test_viz_tooltips.py` extended
- **Spec source:** GitHub issue #26 (acceptance criteria)

## Fixes applied after the review

- **Header reverted to level-wide (Spec finding).** The review found the header silently narrowed to the multiselect selection, contradicting the T3 header semantics and the #26 AC that units with no area "remain in header totals". `areas_query`/`area_name_query`/`fetch_areas` lost the `names` parameter and `app.py` calls `fetch_areas(engine, level)`; the scope/area figures stay national while the choropleth follows the selection. Removed the now-dead names-filtered area-seam tests.
- **`fit_viewstate` degenerate-axis guard (Spec finding).** One-axis-zero spans (a row/column sharing a latitude or longitude) would have hit `ZeroDivisionError` in the zoom log2. The fit now skips zero spans and lets the surviving axis decide; single point still zooms to `MAX_FIT_ZOOM`. Added vertical/horizontal-strip and single-point tests.
- **Trailing newlines (Standards finding).** `viz/choropleth.py`, `viz/viewport.py`, `viz/tooltip.py`, `tests/test_viz_choropleth.py` (plus `viz/app.py` and `tests/test_viz_viewport.py` caught on the same check) ended without a trailing newline — against the T1/T2/T3 review precedent.
- **Border-intersect semantics documented (Spec finding).** `boundary_fill_query` docstring now notes a unit exactly on a shared border intersects both areas and is attributed to each (mirroring the pipeline's `sjoin` intersects), so per-area fills need not reconcile exactly with the header total.

## Standards

**Verified as required:**
- **ACTIVE_UNIT_PREDICATE shared** — `boundary_fill_query` interpolates the single constant, structurally the same set the scatter/header fetch; `test_predicate_matches_the_unit_fetch` pins it.
- **Standby path intact** — the `if missing:` block still renders the empty deck and `st.stop()` before any #26 fetch.
- **Read-direction rule** — grep confirms `etl/` never imports `viz`; only `viz.data` imports `etl.db_schema` (unchanged).

**Hard-ish violation (addressed):** four files ended without a trailing newline (see fixes).

**Baseline smells (judgement calls, consciously weighed):**
- **Duplicated Code (names filter)** — after reverting the header seams, the `AND name = ANY(:names)` block now lives in only `boundaries_query` and `boundary_fill_query`; two copies, not worth a shared helper.
- **Duplicated Code (per-source union)** — `boundary_fill_query`'s per-source loop is a third variant of the `fetch_active_units`/`header_metrics_query` skeleton. Predicate is shared; extraction would touch established T1/T3 seams beyond this change's scope. Kept.
- **Param clump / primitive obsession re-grade** — the `(level, names, active_from, active_to, sources)` clump and the `(sql, params)` tuple seam now have four consumers (the T3 forward-look's trigger). Consciously re-confirmed: the tuple is the repo's established seam contract across 7 builders; bundling into a dataclass is a wider refactor than T4's scope.

Vocabulary ("active units", "capacity MW" kW÷1000, `service.boundaries`) matches CONTEXT.md/ADR 0007. No Feature Envy or Middle Man in the new seams.

## Spec

**Missing or partial:** none after the header revert.

**Scope creep (fixed):** the header had been narrowed to the selection — `areas_query`/`area_name_query`/`fetch_areas` gained a `names` filter and `app.py` passed `selected_names`, silently changing the T3 header contract. Reverted; the multiselect now narrows the choropleth only.

**Implemented but wrong (fixed):**
- `fit_viewstate` crashed on a one-axis-degenerate bounding box (`ZeroDivisionError` in the zoom log2). Guarded; survives strips.
- Border-adjacent units may be counted by two areas (mirrors the pipeline `sjoin` intersect); per-area sums can exceed the header total. Now documented.

**Verified correct:**
- Level selectbox switches grain; Germany = whole-country view (camera 10.45/51.16/6.3, level-0 fill).
- Choropleth colors by live capacity with unit count; hover card for areas reuses the shared `DECK_TOOLTIP` via `source_header`/`unit_body` on the feature properties.
- Multiselect defaults to all and an empty selection means all; unselected areas drop out of the choropleth (feature count == selection size).
- Camera refits to the selected areas' bounding box on level/area change only and survives source/timescope reruns (session state; `should_refit` scope signature).
- Units with no area at the active level render no fill, stay visible as points, stay in header totals (header is level-wide).
- No drill-down interaction.
- All four required unit seams present: boundary/fill SQL + params, GeoJSON join by name (`areas_feature_collection`), viewport-fit math (`fit_viewstate`), and camera-refit decision (`should_refit`).

**Judgement call (kept, documented instead):** the deck preserves the user's framing across reruns because the stored camera makes the deck JSON byte-identical — asserted in the app comment, not by an automated end-to-end test. The AC's seam (when to replace/preserve the stored view) is unit-covered by `should_refit`.

## Summary

- **Standards:** 1 hard-ish violation (trailing newlines) — fixed; 3 judgement-call smells considered, 2 kept, 1 reduced to 2 copies by the header revert that also fixed the Spec finding.
- **Spec:** 2 findings (header scope creep, `fit_viewstate` degenerate crash) plus 1 documentation gap (border double-count) — all closed; no open issues before commit.