# Operational metadata lives in a dedicated `service` schema, not the versioned raw datalake

The extract stage produces two kinds of non-versioned housekeeping data alongside the versioned raw tables: the `loaded_files` load log (load signatures guarding re-extraction) and the level-coded `boundaries` reference layer the transform stage joins against. These live in a dedicated `service` schema (`service.loaded_files`, `service.boundaries`) rather than inside the raw layer, keeping the versioned datalake purely for source records.

## Context

ADR 0004 describes raw as append-only versioned tables and, originally, also placed the boundary reference layer in that schema (`raw.boundaries`). During implementation the boundary reference layer and the `loaded_files` log were moved into a separate schema (first named `serv`, renamed `service`). The raw-versioning semantics — append-only per-source tables, never dropped, load-signature guard — are untouched; only the housekeeping tables moved. The specs and glossary never followed, so every doc still pointed at `raw.boundaries` while the code wrote `service.boundaries`. The review convention (files win, note the discrepancy) and subsequent reviews (multiple code reviews flagged the doc drift) mean the decision itself is sound but the documentation must catch up.

## Decision

Extraction writes the load log and the boundary reference layer into a dedicated `service` schema:

- `service.loaded_files` — the append-only load-signature log (see ADR 0004).
- `service.boundaries` — the single non-versioned, level-coded reference layer (`country_iso='DEU'`, `name`, `level` 0=country outline / 1=regions+EEZ / 2=districts / 3=municipalities, `area` in km² via PostGIS).

`service` is operational metadata, not a pipeline data layer: the data model stays four layers (raw / staging / core / marts); `service` is the side-car the pipeline reads from and writes bookkeeping to. The transform stage spatial-joins against `service.boundaries`; the extract stage records load signatures in `service.loaded_files`.

## Consequences

- The docs must say `service.boundaries` / `service.loaded_files` everywhere an earlier doc said `raw.boundaries` — this ADR supersedes that part of ADR 0004.
- Boundary files remain reference data, loaded once (not versioned). Current extract re-creates `service.boundaries` on each boundary run; ADR 0004's load-if-not-exists guard is documented intent but not yet implemented — a known discrepancy, recorded here rather than silently assumed.
- A future reader sees no undocumented `service` schema in the codebase: its purpose is recorded here, in the glossary, and in the spec's data-layer description.