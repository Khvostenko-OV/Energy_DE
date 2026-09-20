# Code review — Streamlit viz render optimization (docs/Viz_optimazation.md)

- **Date:** 2026-09-20
- **Fixed point:** `c522804` (branch tip, `HEAD`) — uncommitted/staged work under review
- **Diff:** `git diff HEAD` — 9 files, 894 insertions, 900 deletions
- **Commits:** none (working tree, pre-commit)
- **Reviewed artifacts:** `viz/data.py` (pandas ≤2-query fetch, simplified all-area boundaries), `viz/tooltip.py` (+`attach_tooltips`, `_missing`), `viz/choropleth.py` (+`area_fills`, `TRANSPARENT_FILL`, `selected_names`), `viz/header.py` (+`areas_summary`), `viz/app.py` (rewired render flow); tests: `test_viz_data.py`/`test_viz_tooltips.py`/`test_viz_header.py`/`test_viz_choropleth.py` rewritten
- **Spec source:** `docs/Viz_optimazation.md`

## Standards

### Hard violations (documented standards)

None found. Each documented standard was checked against the diff:

- **AGENTS.md "Conventions"** — pytest only, no lint/typecheck targets in scope; the diff keeps seam tests on pytest. ETL stages/ADRs 0005–0007 are untouched (viz still reads `core.generators`/`core.storages` + `service.boundaries`, per ADR 0007).
- **CONTEXT.md / domain.md glossary** — public names stay on-vocabulary ("Storage", "energy_source"); no drift to "Storage unit" or other avoided synonyms.

### Judgement calls (baseline smells)

**Duplicated Code + dead code — `viz/tooltip.py`.** `source_header`/`unit_tooltip` are now production-dead: the app imports only `attach_tooltips` (viz/app.py:92), so they're exercised solely by tests/test_viz_tooltips.py. Meanwhile `attach_tooltips` re-implements the *identical* card formatting in vectorized lambdas (capacity "kW", storage "kWh", `_fmt_date` dates, region·municipality join) — two parallel implementations of one card in one file that can drift (Divergent Change). Prefer `attach_tooltips` delegating to `unit_tooltip` per row, or delete the row API.

**Mysterious Name — `viz/header.py:66`.** `areas_summary` docstring says rows are "the render-opt `optimized_boundaries` rows" — that symbol doesn't exist; the function is `boundaries_query`/`fetch_boundaries`. Stale reference in prose.

**Behavior change smuggled into a render-opt PR — `viz/data.py`, `ACTIVE_UNIT_PREDICATE`.** The timescope predicate flipped from `commissioning_date <= :to AND decommission >= :from` to `commissioning_date >= :from AND decommission >= :to`. Tests correctly repin the new SQL (test_viz_data.py `TestUnitsQuery`), so behavior is pinned — but a render-optimization change silently redefines what the timescope means. Worth an explicit note/issue; the design doc `docs/Viz_optimazation.md` still projects `unit_id` (lines 10/20) that the implementation dropped — inline rationale exists, but AGENTS.md's "note the discrepancy" spirit suggests surfacing it.

**Data Clumps — selection narrowing triplicated.** `frozenset(selected_names)`/`name_set` recurs in viz/app.py (`selected_set` camera filter), `areas_feature_collection`, and `areas_summary`; a change to selection semantics touches three seams.

**Test nits.** `test_selected_names_can_be_passed_as_a_set` passes a tuple, not a set; `test_areas_sort_alphabetically` pins groupby ordering the app implicitly relies on for layer order. Both accurate; names slightly misleading.

**Removed-code check** — `boundary_fill_query`/`header_metrics_query`/`areas_query`/`fetch_areas` are fully deleted, imports cleaned; no leftover references. `run_query` retained (still used by `fetch_area_names`/`fetch_boundaries`).

## Spec

### (a) Missing or partial
- Spec §1.2: "Add column 'tooltip'". Implemented as two columns, `source_header` + `unit_body`, never one named `tooltip` (`viz/tooltip.py:attach_tooltips`). Faithful to the pre-existing `DECK_TOOLTIP` shape, so partial, not broken.
- Spec §1.3: "boundaries … to boundaries df" — `fetch_boundaries` returns a list of dicts, not a DataFrame (`viz/data.py:fetch_boundaries`). Cosmetic.
- Spec §1.1 empty skeleton carries `unit_id`; both projections now drop it. Trivial.
- Everything else the doc demands is present and correctly wired: ≤2 unit queries (`_needed_tables` skips generators iff no non-storage source); `area_column AS name`; name groupby replaces `ST_Intersects`; boundaries cover all areas with selected fill from `area_fills`; area card = name for all, capacity+units for selected; header sums/counts the frame so no-name (offshore) units stay in header totals while dropping from fills, exactly per the design note.

### (b) Scope creep (not asked for)
- `ST_SimplifyPreserveTopology(geometry, 0.001)` + payload-thinning `BOUNDARY_SIMPLIFY_TOLERANCE` (`viz/data.py`). The doc's optimisation is query count/join removal; geometry alteration is an extra, undocumented change.
- Camera fit narrowed to `selected_set` (`viz/app.py:284-290`). Behavioural change absent from the doc.
- `_serializable_units`/NaN→None JSON normalization and the `unit_id`/`district` drops — collateral beyond the brief.

### (c) Implemented but looks wrong
- **Tooltip "active" contract silently broken.** `unit_tooltip` renders missing dates as `Commissioning: active` (fallback), but `attach_tooltips` emits `"" if _missing(v)…`, so the line vanishes entirely (`viz/tooltip.py`). The app renders via `attach_tooltips`, yet `.test_nat_decommissioning_reads_active` pins only `unit_tooltip` — the render path isn't the tested path. Spec §1.2's tooltip column content diverges by seam.
- **Unit-count drift:** `area_fills` uses `.count()` on `installed_capacity` (drops NULL rows) while the header uses `len(units)`, so a NULL-capacity unit counts in the header but not its area fill. Old `COUNT(u.unit_id)` didn't have this gap.
- **Reconciliation untested:** the key spec note (no-name units in header but not fills) is asserted only piecemeal; ex-`fetch_header_metrics` SQL pinning was removed with no test on the new `sum()/len()` totals.

## Summary

**Standards:** 0 hard violations, 5 judgement calls (dead/duplicated tooltip card, stale `optimized_boundaries` docstring, predicate-flip note, triplicated selection narrowing, 2 misleading test names); worst issue: the two divergent implementations of one hover card in `viz/tooltip.py` (`unit_tooltip` vs `attach_tooltips`) that can drift. **Spec:** 9 findings (3 missing/partial, 3 scope creep, 3 looks-wrong); worst issue: the tooltip render path silently drops missing-date "active" lines while the pinned `unit_tooltip` path keeps them — the seam pydeck actually renders is untested.