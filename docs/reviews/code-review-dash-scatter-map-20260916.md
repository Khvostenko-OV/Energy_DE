# Code review — Dash scatter map skeleton (#18)

- **Date:** 2026-09-16
- **Fixed point:** `HEAD` (38712c9) — review of the uncommitted working tree (committed after review)
- **Diff:** `git diff HEAD` + new untracked files (`viz/{__init__,palette,data,figure,app}.py`, `requirements-viz.txt`, `tests/test_viz_figure.py`, `tests/test_viz_data.py`)
- **Spec source:** GitHub issue #18 (fetched via `gh issue view 18`)
- **Reviewed artifacts:** new `viz/` package — palette constants (`viz/palette.py`), PostGIS read path (`viz/data.py`), `build_units_map` figure builder (`viz/figure.py`), Dash entrypoint on port 8050 (`viz/app.py`), `requirements-viz.txt`, and unit + integration tests

## Standards

1. **Duplicated Code (fixed) — query shape written twice.** `fetch_generators` / `fetch_storages` re-encoded the same `SELECT {columns} FROM core.{table} ORDER BY longitude, latitude` shape, differing only in table + column tuple — the exact "query written a second time" finding the #17 review extracted into a shared helper. **Fixed:** `_fetch(table, columns, engine)` in `viz/data.py`; both fetch functions delegate.

2. **Duplicated Code (fixed) — identical source loops.** `build_units_map`'s generator and storage loops were line-for-line identical except the fallback symbol. **Fixed:** extracted `_add_source_traces(fig, df, symbol)`; both kinds share it.

3. **Mysterious Name / collision (fixed).** `viz.data.STORAGE_COLUMNS` collided semantically with `etl/db_schema.STORAGE_COLUMNS` (which means `("storage_type", "storage_capacity")`, something else). **Fixed:** renamed to `GENERATOR_QUERY_COLUMNS` / `STORAGE_QUERY_COLUMNS`.

4. **Speculative Generality (judgement call, accepted).** The per-category `MARKER_SYMBOLS` map was constant — only `storage` differed — so the fallback in the storage loop was dead. Dropped the map; the two exposed constants (`GENERATOR_MARKER_SYMBOL`, `STORAGE_MARKER_SYMBOL`) plus the kind-driven helper carry the distinction.

5. **Speculative Generality (judgement call, suppressed).** `"diesel"` in `ENERGY_COLORS` is not in core today — but the issue's AC3 *requires* the palette to cover all 7 categories and names diesel explicitly, so the spec overrides the baseline.

6. **Divergent Change (judgement call, accepted).** `viz/data.py` re-invokes `load_dotenv` that `etl/config.py` already does. Kept: `viz` runs standalone (`python -m viz.app`, gunicorn), `VIZ_DATABASE_URL` is an app-specific knob, and `load_dotenv` is idempotent.

7. **Scope drift in docstrings (noted, not changed).** `viz/__init__.py` claims "#18-#20" and `viz/palette.py` claims to be the home of "the choropleth fills and the chart strip". The consuming tickets exist (#19/#20) and the issue text itself says the palette's colors are "reused later by the choropleth and charts", so the claim is grounded, not speculative. Recorded for the #19/#20 work.

8. **Recorded, not a violation.** `gunicorn` in `requirements-viz.txt` is unused until the #21 image; AGENTS.md still documents Metabase as the dashboard stack. Both were already recorded in the #17 review §4 (the spec/issue now supersedes).

## Spec

All six acceptance criteria satisfied.

| AC | Result |
|----|--------|
| Dash entrypoint serves MapLibre `go.Scattermap` on `open-street-map` with clustering at `localhost:8050` | ✅ `viz/app.py` (port 8050), `build_units_map` → `go.Scattermap` traces, `fig.update_maps(style="open-street-map")`, `cluster=dict(enabled=True, step=50)` on every trace; GET / 200 via the Flask test client and `app.run(port=8050)` |
| Data layer returns full column set for generators and storages (lon/lat, energy_source, capacity, dates, region keys) | ✅ `fetch_generators` / `fetch_storages` (`_fetch`) with `GENERATOR_QUERY_COLUMNS` / `STORAGE_QUERY_COLUMNS`; integration tests assert exact column sets + row counts vs core |
| Curated palette covers all 7 categories, single shared constant; storages use distinct marker | ✅ `ENERGY_COLORS` (7 keys incl. diesel) + `DEFAULT_COLOR` in `viz/palette.py`; `STORAGE_MARKER_SYMBOL="diamond"` vs `GENERATOR_MARKER_SYMBOL="circle"` |
| `requirements-viz.txt` pins `dash`, `plotly>=6.1,<7`, `gunicorn`; pipeline `requirements.txt` unchanged | ✅ new file, pipeline `requirements.txt` untouched |
| Unit test: figure builder makes a valid plotly figure from synthetic DataFrames (traces, palette lookup, marker assignment) | ✅ `tests/test_viz_figure.py` (14 tests) |
| Integration test: query functions return expected rows/columns against live DB | ✅ `tests/test_viz_data.py` (13 tests, drops/loads core like the other core-consuming modules) |

Findings triaged:

- **Storage hovercard dropped `installed_capacity` (fixed).** The hovercard showed only `storage_capacity` ("—" when null) even though the query returns the installed capacity. Real null-capacity storages exist (`"storage_capacity <= 0 or null"` is a documented collision, `db_schema.py`). **Fixed:** storage hovercards now show both `Storage capacity` (kWh) and `Installed capacity` (kW); generators show installed capacity only.
- **AC4 "pins" (accepted).** Only `plotly` carries an explicit bound (`>=6.1,<7`), matching the issue text verbatim (the issue names the bound for plotly alone); dash/gunicorn stand bare as the issue writes them.
- **Scope beyond ACs (accepted).** Per-unit HTML hovercards, a Germany-centered initial camera/zoom, the `DEFAULT_COLOR` fallback, and `VIZ_DATABASE_URL` engine selection go beyond the letter of the ACs — the first two serve the issue's "interactive, zoomable map" and the last anticipates the seed's `viz_reader` role the issue names; kept.
- **Marker/color consistency for non-canonical source (accepted).** A storage row whose `energy_source` is not exactly `"storage"` renders diamond-but-`DEFAULT_COLOR`; the integration test locks storage `energy_source` to `{"storage"}`, and the fallback keeps an unexpected source visible — recorded as intentional.

```text
Summary: Standards — 8 findings (4 fixed, 2 accepted judgement calls, 2 recorded notes), worst Duplicated Code (query shape). Spec — all 6 ACs met; 1 finding fixed (storage capacity hovercard), 3 accepted (AC4 pinning, scope additions, fallback consistency).
```