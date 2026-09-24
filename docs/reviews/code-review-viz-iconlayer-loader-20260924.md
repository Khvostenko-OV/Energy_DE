# Code review — Viz IconLayer + sprite data-URI loader (feat/icons)

- **Date:** 2026-09-24
- **Fixed point:** `main` (`265d23a`) — review of `f12e5db`, then the follow-up review fix `502c220`
- **Diff:** `git diff main...HEAD` (@ review time: commit `f12e5db`) — 11 files, 168 insertions, 43 deletions; follow-up fix `502c220`
- **Commits:** `f12e5db` (IconLayer + loader), `502c220` (auto-pack fix)
- **Reviewed artifacts:** `viz/icon_atlas.py` (new loader seam), `viz/map_builder.py` (`build_source_layers` − ScatterplotLayer → + IconLayer), `tests/test_viz_{icons,map_builder,palette}.py`, README.md + five viz modules (scatter→unit-layer wording sweeps)
- **Spec source:** conversational request (no GitHub ticket): inline the per-source sprites as base64 data URIs; swap the per-source unit layers to deck.gl IconLayer over those sprites; preserve palette tint, paint order, layer ids, pickable tooltips, unknown-source fallback; pin the new contract in tests.
- **Standards sources:** AGENTS.md + CONTEXT.md + ADRs + existing `viz/*.py`/test conventions + Fowler smell baseline (Refactoring ch.3)

Two-axis review: **Standards** (conformance + smells) and **Spec** (faithful implementation), deliberately kept separate.

---

## Standards

**No hard violations.** All new/changed modules carry issue-numbered docstrings and `from __future__ import annotations` (AGENTS.md); `viz.icon_atlas` uses stdlib only (runtime stays distroless/Pillow-free); tests stay DB-free; clarifying-only comments; trailing newlines at EOF.

### Baseline smells (judgement calls)

- **Duplicated Code:** `png_size` was byte-identical in `viz/icon_atlas.py` and `tests/test_viz_icons.py`. → **Fixed** (`502c220`): tests now import the production seam they exercise.
- **Duplicated Data:** `get_icon=dict(url=atlas, …)` and `icon_atlas=atlas` embedded the same base64 sprite twice per layer. → **Fixed** (`502c220`): `icon_atlas` prop removed (also the rendering bug, see Spec).
- **Middle Man (minor):** `_sprite_path` is a thin wrapper over `icon_png_path` adding the alphabetical fallback. → **Kept.** The wrapper is the single choke point that keeps the two cached loaders consistent for unknown sources; the name is honest.
- **Aside (not a smell):** `png_size`/`icon_size_px` used `assert` for PNG-magic/squareness validation, which silently vanishes under `python -O`. → **Fixed** (`502c220`): explicit `ValueError`.

## Spec

**One critical finding, since fixed; everything else compliant.**

- **(c) Implemented but wrong — invisible icons:** the layer sent a *string* `iconAtlas` (the data URI) with a constant `get_icon` `{url,width,height,mask}` and no `iconMapping`. deck.gl's IconLayer `updateState` early-returns on a string `iconAtlas`; it then resolves every icon through `getIconMapping` against the (empty) mapping, returning `MISSING_ICON` (`{x:0,y:0,width:0,height:0}`, confirmed in the bundled deck.gl) → zero-size frames, units render silently invisible. The documented auto-packing path (no `iconAtlas`; `getIcon` carries the url/size/mask def) is what satisfies the request as written. → **Fixed** (`502c220`): `icon_atlas` dropped, auto-packing used; the serialized deck spec is now asserted free of `iconAtlas`, and `get_icon.width == manifest cell` is pinned (previously only `width == height > 0`).
- **(a) Test gap:** icon-prop assertions read the in-memory pydeck object only, never the serialized spec. → **Fixed:** `test_serialized_spec_auto_packs_the_sprite` decodes `Deck.to_json()`.
- **(b) Scope creep (cosmetic):** docstring/README "scatter"→"unit layer" rewording in behaviour-untouched files. → **Kept as deliberate** (part of the agreed plan; keeps module docs truthful).

Everything else verified: loader contract (data-URI prefix, PNG magic, byte-exactness), palette tint/mask/opacity, `SOURCE_LAYER_ORDER` paint order, `<source>-units` ids, `"[longitude, latitude]"`, `pickable`, unknown-source fallback, and the loader/size tests themselves.

---

## Summary

- Standards: 4 findings (2 fixed, 1 kept, 1 fixed-as-aside) — worst was the missing-EOF/`png_size` duplication pattern, now clean.
- Spec: 1 critical rendering bug (fixed in `502c220`), 1 test gap (fixed), 1 cosmetic scope note (kept deliberate).
- Outcome: `336 passed`, committed as `502c220` on `feat/icons`.