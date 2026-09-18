# Code review — Streamlit viz T3 header aggregates (issue #25)

- **Date:** 2026-09-18
- **Fixed point:** `800f06f` (current branch tip, `HEAD`) — uncommitted/staged work under review
- **Diff:** `git diff HEAD` plus untracked new files `viz/header.py` and `tests/test_viz_header.py` — 7 files, 350 insertions, 12 deletions
- **Commits:** none (working tree, pre-commit)
- **Reviewed artifacts:** `viz/header.py` (new), `viz/data.py` (+`ACTIVE_UNIT_PREDICATE`, `_unit_table`, `areas_query`/`area_name_query`/`fetch_areas`, `header_metrics_query`/`fetch_header_metrics`), `viz/config.py` (+`LEVEL_INDEX`), `viz/app.py` (+sidebar drill level, header render), `tests/test_viz_header.py` (new), `tests/test_viz_data.py` extended, `tests/test_viz_config.py` extended
- **Spec source:** GitHub issue #25 (acceptance criteria); blocked-by #24 (CLOSED) done, #26 (levels/area selection/choropleth) explicitly out of scope
- **Standards sources:** AGENTS.md + CONTEXT.md + ADRs (0001–0007) + existing `etl/*.py` + `viz/*.py` conventions + Fowler smell baseline (Refactoring ch.3) + T1/T2 review precedent (`code-review-streamlit-viz-t1-20260918.md`, `code-review-streamlit-viz-t2-20260918.md`)

Two-axis review: **Standards** (conformance + smells) and **Spec** (faithful implementation), deliberately kept separate.

---

## Standards

**No hard violations after fixes.** Issue-numbered docstrings on the new/modified modules (AGENTS.md); `from __future__ import annotations` in `viz/header.py`; the read-direction rule holds (`etl` never imports `viz`; only `viz.data` imports `etl.db_schema`); all new SQL is bound-parameterised (`:level`, `:source_n`); vocabulary matches CONTEXT.md (`service.boundaries` level encoding per ADR 0007; kW→MW ÷1000 per "Installed capacity").

### Baseline smells (judgement calls)

- **Duplicated Code: predicate + table dispatch were copied verbatim from `unit_query`/`fetch_active_units` into `header_metrics_query`/`fetch_header_metrics`** — a drift between the map's active set and the header's would silently diverge. → **Fixed after review:** extracted the shared `ACTIVE_UNIT_PREDICATE` constant and `_unit_table` helper; both query seams now compose the identical WHERE clause from one definition, making the "same predicate" promise structural (and the parity test stays).
- **Duplicated Code: `format_mw` and `format_area_km2` are byte-identical, and `scope_title` inlines a third thousands-separator. → Kept.** The spec mandates three distinct formatting seams ("MW/count/area formatting"), so they stay separate public functions; the shared body is a one-line format spec, and the units live in the caller's metric labels, not the formatter.
- **Data Clump: the {chooser label → numeric level} map re-codes the T2-flagged label/table coupling; adding a level touches `MAP_LEVELS`, `LEVEL_INDEX` and the boundary data. → Kept.** Contained to `viz.config` and deliberately index-locked by tests in both suites.
- **Duplicated Code (tests): `TestLevelConfig` (test_viz_header.py) repeats `TestLevelDefaults` (test_viz_config.py) assertions on `LEVEL_INDEX`. → Kept.** Belt-and-braces pinning of the one constant the header depends on.
- **Primitive Obsession: the `(sql, params)` bare tuple now has six seams (up from two at T2). → Kept.** Still a local two-item contract between query builders and `run_query`; re-grade if a fourth consumer of the query-building seam appears.

**Fixed after review:** two new files (`viz/header.py`, `tests/test_viz_header.py`) had missing trailing newlines (a pattern T1/T2 reviews already flag) → added.

## Spec

**Verdict: all 6 acceptance criteria implemented and seam-tested; the four header figures are fetched from the same predicate the map renders.**

**(a) Missing / partial** —
- AC5 "All header values recompute on source/timescope/level changes": the two area figures (count, km²) are driven solely by the drill level — sources/timescope cannot change them, because at T3 the map renders no areas (that is #26). The spec's "current selection and shared filters" reading is satisfied: every Streamlit rerun refetches all four values, and the unit metrics plus the scope respond to every widget. → **Recorded decision, kept.** The area scope is level-scoped by definition until T4 adds area selection.
- AC1 "showing the area name when exactly one area is selected (e.g. `Region Berlin`)": under T3 scope only the country level has exactly one area, so the live header shows the bare name ("Germany"); the prefixed `Region Berlin` form is exercised by the seam tests (`scope_title`/`single_area_title`) and becomes reachable when #26 adds area selection. → **Kept.** Implementing the seam now is spec-literal ("pytest unit seams cover: … the single-name header case"); the showcase case is structurally T4's entry point.

**(b) Scope creep** —
- Sidebar **"Drill level"** selectbox was not explicitly named by #25, but AC5 requires the header to "recompute on … level changes", and without a level control the level can't change. It defaults to option 0 = `INITIAL_LEVEL` ("Germany", config-locked by tests). → **Kept, minimal.** The full selection/choropleth machinery stays with #26.

**(c) Implemented but looks wrong** —
- MW formatting rounds to whole MW (`:,.0f`): a selection summing < 0.5 MW reads "0 MW" while the map still renders those units. → **Kept.** Unit count sits one metric away; the tooltip shows kW; sub-0.5 MW selections are an artefact of an extreme filters combination, not a realistic scope.
- `header_metrics_query` re-embeds the #24 predicate rather than aggregating the already-fetched `units` dict. → **Fixed as part of the predicate dedupe above**; the header and map now share one `ACTIVE_UNIT_PREDICATE` definition, so the "match what the map renders" guarantee is structural rather than duplicated text.

## Summary

- **Standards:** 0 hard violations after 2 fixes (trailing newlines; shared predicate/table-dispatch extraction for the worst duplication); 5 judgement-call smells kept, worst is the now-mitigated map/header predicate duplication.
- **Spec:** 0 missing, 1 recorded decision (area figures are level-scoped until #26), 1 scope-creep item kept deliberately (drill level, required to satisfy AC5), spec-parity guarantee made structural.