# Code review — Streamlit viz T1 tracer (issue #23)

- **Date:** 2026-09-18
- **Fixed point:** `2c6d82b` (current branch tip, `HEAD`) — uncommitted/staged work under review
- **Diff:** `git diff --cached HEAD` — 10 new files, 383 insertions (plus one follow-up AGENTS.md edit)
- **Commits:** none (staged, pre-commit)
- **Reviewed artifacts:** `viz/` package (`__init__`, `config`, `palette`, `data`, `map_builder`, `app`), `tests/test_viz_{config,data,map_builder}.py`, `requirements-viz.txt`
- **Spec source:** GitHub issue #23 (acceptance criteria), VisualizationSpec.md v3.0, follow-up issue #24
- **Standards sources:** AGENTS.md + CONTEXT.md + ADRs (0001–0007) + existing `etl/*.py` conventions + Fowler smell baseline (Refactoring ch.3)

Two-axis review: **Standards** (conformance + smells) and **Spec** (faithful implementation), deliberately kept separate.

---

## Standards

**No hard violations.** All ten modules/tests carry issue-numbered docstrings (AGENTS.md); `viz/*.py` use `from __future__ import annotations`; the read-direction rule holds (only `viz.data` imports `etl.db_schema`; `etl` never imports `viz`); comments carry real rationale; tests are pytest-style; domain vocabulary matches CONTEXT.md; the `BOUNDARY_LEVEL_COLUMNS` reference in `viz/config.py` resolves to a real constant.

**Judgement call / near-miss:** the viz unit seams import `pydeck` at collection time, so the base pytest suite now needs `requirements-viz.txt` installed. → Addressed after review: AGENTS.md (Stack, install gotcha, Verification) now documents the viz runtime requirement.

### Baseline smells

- **Speculative Generality (headline):** `viz/palette.py` is entirely unused in T1; `viz/config.py`'s timescope/sources/level constants are consumed only by tests. → **Resolved-by-spec:** AC1 explicitly requires the palette module, and the issue text requires those config defaults to live in a config module; the Spec axis independently confirmed these are #24 cells baked into the T1 contract. Kept as mandated.
- **Duplicated Code / Shotgun Surgery:** the canonical source tuple exists in `config.DEFAULT_SOURCES` (display order) and `palette.SOURCE_LAYER_ORDER` (paint order, reversed by design). Adding a source touches etl + two viz modules. → Judgement call: the orders are deliberately inverse and comments state the relationship; unifying them now would couple two stack-order concerns. Left for T2 when the sidebar actually consumes both.
- **Data Clumps:** the `(lon, lat, zoom)` view-state triple travels as a dict + a scalar and three `build_deck` params. → Judgement call: a single `ViewState` in config would couple config to pydeck; the drill tickets (#25+) can formalize this.
- **Broad `except Exception` (`viz/app.py`):** masked any bug (e.g. a missing `DATABASE_URL` KeyError) as "tables missing". → **Fixed after review:** narrowed to `sqlalchemy.exc.SQLAlchemyError`, documented in a comment; misconfiguration now fails loudly.
- **Unbound schema literal in SQL (`viz/data.py`):** `CORE_SCHEMA` interpolated into the query text. → **Fixed after review:** bound as the `:schema` parameter.
- **Trivial:** unused `import pytest` in `tests/test_viz_data.py` → removed; missing trailing newlines in all new files → added.

## Spec

**Verdict: all 5 acceptance criteria plus the config-defaults mandate are implemented; no material requirement is missing.**

**(a) Missing / partial** — none. AC1's four modules exist; AC4's load-command copy appears verbatim (`viz/app.py`: "No core tables … Load them with `python -m etl run-all`"); AC5's seams (config defaults, standby detection, empty-deck builder, engine seam) each have a test module. The config mandate (timescope `1900-01-01`→today, all sources checked, initial level Germany) is present; the Light basemap is the tokenless CARTO Positron GL URL; `get_viz_engine` implements the VIZ→DATABASE fallback. Minor: standby detects presence, not row-count — an empty-but-present `core.generators`/`storages` shows the live UI; the spec only requires *absence*, so acceptable.

**(b) Share / scope creep** — none of #24's behaviour leaked in (no scatter layers, checkboxes, check-all, timescope filtering, tooltips, unit queries). Two constants pre-stage #24 data (`palette.ENERGY_COLORS`/`SOURCE_LAYER_ORDER`, `MAP_LEVELS`) but are spec-required modules/defaults; a single-entry map-style selectbox (`viz/app.py`) is minor extra UI but matches the VisualizationSpec Layout. Kept.

**(c) Implemented but wrong** —
- Broad `except Exception` caught `KeyError` from a missing `DATABASE_URL` and genuine bugs, misreporting them as "tables are missing" while the issue only merges an unreachable DB into the standby notice. → **Fixed after review:** narrowed to `SQLAlchemyError`.
- `CORE_SCHEMA` interpolated bare into SQL. → **Fixed after review:** bound parameter.

## Summary

- **Standards:** 2 hard-ish findings (broad exception, unbound SQL literal) + 3 judgement calls; worst before review: the masking `except Exception`. Both hard findings fixed; judgement calls intentionally kept, each with a reason.
- **Spec:** 0 missing, 0 wrong after the two fixes; worst issue: standby message overstating which tables are absent when the DB itself is unreachable (acceptable per the issue's merged-notice requirement).