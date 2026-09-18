# Code review — Streamlit viz T2 scatter units (issue #24)

- **Date:** 2026-09-18
- **Fixed point:** `f4b8c87` (current branch tip, `HEAD`) — uncommitted/staged work under review
- **Diff:** `git diff --cached f4b8c87` — 9 files, 622 insertions, 20 deletions (plus follow-up review fixes)
- **Commits:** none (staged, pre-commit)
- **Reviewed artifacts:** `viz/` package additions (`data.py`, `map_builder.py`, `palette.py`, `tooltip.py` new, `app.py`), `tests/test_viz_{palette,tooltips}.py` new, `tests/test_viz_{data,map_builder}.py` extended
- **Spec source:** GitHub issue #24 (acceptance criteria), VisualizationSpec.md v3.0 (`layout` sidebar/time-scope/map-window cells)
- **Standards sources:** AGENTS.md + CONTEXT.md + ADRs (0001–0007) + existing `etl/*.py` conventions + Fowler smell baseline (Refactoring ch.3) + T1 review precedent (`code-review-streamlit-viz-t1-20260918.md`)

Two-axis review: **Standards** (conformance + smells) and **Spec** (faithful implementation), deliberately kept separate.

---

## Standards

**No hard violations.** All new/modified modules carry issue-numbered docstrings (AGENTS.md); `viz/*.py` use `from __future__ import annotations`; the read-direction rule holds (`etl` never imports `viz`, only `viz.data` imports `etl.db_schema`); pytest-style tests; domain vocabulary matches CONTEXT.md; the predicate SQL is bound-parameterised (no unbound interpolation — the T1 finding stays fixed).

### Baseline smells (judgement calls)

- **Duplicated Code / Shotgun Surgery:** the canonical source set lives in `palette.SOURCE_LAYER_ORDER` (paint order) + `config.DEFAULT_SOURCES` + the sidebar mirror `app.SOURCE_DISPLAY_ORDER` (reversed); adding a source touches etl + three viz modules. → **Kept.** The T1 review explicitly deferred this coupling to T2; the orders are deliberately inverse stack concerns and the sidebar mirrors the palette, so unifying now would couple two different orderings. Revisit if a third consumer appears.
- **Feature Envy:** `app.py` mutates fetched rows with `row["tooltip"] = unit_tooltip(row)`. → **Kept.** That is app glue between the fetch seam and the render seam; the tooltip string itself stays owned by `viz.tooltip`.
- **Primitive Obsession:** `(sql, params)` shuttles as a bare tuple between `unit_query` and `run_query`. → **Kept.** A two-item local contract with exactly two call sites; a wrapper type would be premature abstraction.
- **Mild Feature Envy (misc):** `hex_to_rgba` lives in `map_builder` though the hex values originate in the palette. → **Kept.** RGB(A) is the deck.gl layer representation, so the conversion belongs beside the layer builder, not the colour catalogue.

**Fixed after review:** three files (`viz/tooltip.py`, `tests/test_viz_palette.py`, `tests/test_viz_tooltips.py`) had missing trailing newlines (a pattern the T1 review already flagged) → added.

## Spec

**Verdict: all 6 acceptance criteria implemented; the unit-info contract, predicate SQL, and seam tests match the spec verbatim.**

**(a) Missing / partial** —
- AC4 edge: a storage row whose `storage_capacity` is NULL (the loader *flags*, doesn't repair — `etl/load.py` `STORAGE_CAPACITY_COLLISION_REASON`) renders a card without the storage line. The "storages differ correctly" contract holds for the loaded data; the missing-capacity case falls back to a plain unit card. → **Judgement call, kept.** No capacity to display; omitting the line is honest.
- AC1 edge: with check-all off and nothing checked, the app still runs the (empty) fetch/render path and produces a deck with zero layers. Harmless — the map visibly empties. → Kept.

**(b) Scope creep** —
- Fixed `UNIT_RADIUS_M` and opacity were not requested (the spec only bans *viewport culling/cap*). Sizing is a render choice needed to make 80k+ points legible at country zoom. Radius kept.
- **Opacity diluted the palette colour** ("each in its fixed palette color"): a translucent variant of the hex was passed. → **Fixed after review:** fill color is now the opaque palette RGB (`#1e88e5` → `(30,136,229,255)`), matching AC1 literally.
- `disabled=not select_all` grey-out of per-source boxes — a UI nicety beyond the checkbox list. Kept.

**(c) Implemented but looks wrong** —
- **Check-all vs per-source desync:** toggling `sources_all` off/on resets any individually-deselected sources (master-switch semantics). The "check-all toggles the whole set" AC3 is satisfied; the loss of earlier individual picks on a master re-toggle is the standard master-switch trade-off. → **Kept as designed.**
- **`_fmt_date` "active" fallback for a null `commissioning_date`** reads "Commissioning: active". The spec's parenthetical `("active" when null)` covers *commissioned and decommissioned* dates verbatim, so the implementation is spec-literal; core has no active units with a null commissioning date in practice. → Kept (noted as a semantic wrinkle if null commissioning dates ever enter core).

## Summary

- **Standards:** 0 hard violations; 4 judgement-call smells (worst: the sidebar/palette source-order coupling, T1-deferred and still deliberated) + 1 trivial newline fix applied.
- **Spec:** 0 missing, 0 wrong after one fix (opaque palette color); 4 kept judgement calls; the predicate SQL, defaults, tooltip contract, and all six AC seams verified against the spec verbatim.