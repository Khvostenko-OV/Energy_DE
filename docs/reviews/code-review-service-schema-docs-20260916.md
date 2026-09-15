# Code review — Issue #12 docs sweep (`service` schema)

- **Date:** 2026-09-16
- **Fixed point:** `d544573` (HEAD before the sweep)
- **Diff:** `git diff d544573` — 8 files: AGENTS.md, CONTEXT.md, README.md, TechnicalSpecification.md, docs/adr/0004, docs/adr/0006, docs/adr/0007 (new), etl/db_utils.py — 77 insertions, 58 deletions
- **Commits:** uncommitted working tree (single changeset)
- **Reviewed artifacts:** all doc changes of the docs sweep (issue #12) + the one etl/db_utils.py docstring edit
- **Spec source:** https://github.com/Khvostenko-OV/Energy_DE/issues/12 (4 acceptance criteria)
- **Standards sources:** AGENTS.md + CONTEXT.md + ADRs 0004/0006/0007 + TechnicalSpecification.md + docs/reviews/ house style

Two-axis review: **Standards** (conformance + smells) and **Spec** (faithful implementation), deliberately kept separate.

---

## Standards

**Summary — 3 hard, 1 smell (all fixed in this round).**

Hard findings (violating documented homegrown standards — AGENTS.md: "where the spec and files conflict, the files/source datasets win"; "note the discrepancy rather than silently assuming"; house style for ADR supersession):

1. **AGENTS.md "Verification" fabricated a CI claim.** The section asserted "CI is smoke-only: dependencies install, modules byte-compile, and the pipeline image builds" — but no `.github/` workflow and no `Dockerfile` exist anywhere in the repo (Docker + GitHub Actions are `-- planned` per the same file's Stack row, tickets #13/#14). The verification bar is the pytest suite; the CI plan is aspirational. **Fix:** rewrote the section to report only what exists (pytest, no linters/typecheckers) and state that Docker + CI are planned (#13–#16). AGENTS.md now makes no claim CI exists.

2. **ADR 0007 asserted a boundary re-extraction guard that does not exist.** The new ADR's Consequences claimed "the re-extraction guard (`-f` force flag) applies to unit sources only and does not recreate/replace boundary reference data on routine re-runs" — false: `extract.py` writes `service.boundaries` with `if_exists="replace"` unconditionally and `run_all` always re-runs it, so every boundary run wipes and recreates the table (orig. extract.py:192–196 / current extract.py:232–236). **Fix:** ADR 0007 now states the actual behavior (recreated on each boundary run) and records ADR 0004's load-if-not-exists guard as documented-but-unimplemented intent — a known discrepancy, noted rather than silently assumed. The language matches the reviewer convention the earlier `extract-v2` review established (finding (a) there flagged the missing guard).

3. **ADR 0004's "load-if-not-exists" went unreconciled.** The terms-of-the-sweep, which edited ADR 0004, restated a known-false behavior description even though the discrepancy is a standing, previously-flagged gap (see `code-review-extract-v2-20260912.md`). Arguing "the sweep wasn't about the guard" is the shotgun-surgeon's retreat; the whole point of the sweep is that every doc must read truthfully. **Fix:** added a short supersession note (ADR 0007) to ADR 0004 that a) relocates `boundaries`/`loaded_files` to the `service` schema per the new ADR and b) flags the load-if-not-exists guard as documented intent the current extract has not implemented. ADR 0004's original decision text is untouched (it is a historical record), only annotated.

Smell (per Refactoring book smell list — deliberate divergence, not a bug):

4. **ADR 0006 still described storages in future tense.** "Storages get their own `storage_properties` / `storage_units_properties` when `core.storages` lands (issue #7)" / "The storage kind gets … when it lands" — storages landed in the previous PR. **Not a hard violation:** the "when it lands" phrasing is a historical *Context* note inside ADR 0006, so it's load-bearing as decision history. But given the sweep's mandate (docs must read as truth today), leaving past-tense history next to future-tense assertions is a smell — the sweep's AGENTS/README rows about storages that *did* land sit adjacent to an ADR claiming they haven't. **Fix:** reworded those two sentences to past tense ("have their own", "The storage kind has …") — history preserved, tense made innocent.

5. **Spec's dimension-table naming drift.** The spec's Staging "Dimension tables (one set for each Unit table)" used `properties`/`units_properties`/`param_id` while the code and ADR 0006 use per-kind tables `{source}_properties`/`{source}_units_properties` (staging) and `generator_properties`/`storage_properties` (core) with `prop_id`. The sweep renumbered the spec's data-layer mapping and touched the raw/staging/core/marts sections, so leaving per-kind naming drift there would have restated a contradiction in a touched section. **Fix:** updated Staging to `{source}_properties`/`{source}_units_properties` and Core to per-kind names with `prop_id`, matching the db_utils DDL (staging `param_id`, core `prop_id`).

---

## Spec

**Source:** issue #12 acceptance criteria.

**Summary — all four ACs met; no scope creep.**

**AC1 — Record the decision in an ADR: `service` is operational metadata, not a data layer.** Fully met. ADR 0007 defines `service.loaded_files` + `service.boundaries`, states `service` is the side-car the pipeline reads from and writes bookkeeping to, keeps the model four layers, and supersedes the corresponding part of ADR 0004. It reads like the house ADRs (Context/Decision/Consequences, trade-off noted), and its "known discrepancy" wording now correctly defers to the not-yet-implemented load guard.

**AC2 — Glossary Raw entry: drop `boundaries`; add Service.** Fully met. CONTEXT.md Raw entry now records-only ("Records only — … versions and files live in the Service schema"), and a new Service term entered. `raw.boundaries` / `raw.loaded_files` are gone from CONTEXT/README/TechnicalSpecification; the only remaining mentions are the ADR 0007 history paragraph and dated review files (both legitimate).

**AC3 — Glossary/README/spec point at `service.*`.** Fully met. TechnicalSpecification.md's extract step reads `service.boundaries`; README's pipeline text, spec's data-layer mapping (Raw / Service operational metadata / Staging / Core / Marts), ADR 0004, ADR 0007 and CONTEXT all now speak `service.*`.

**AC4 — README/AGENTS report reality: implemented pipeline, six sources, storage property tables landed.** Fully met. README Status "Implemented"; AGENTS data row "6 sources loaded", gotchas updated; README step 3 lists `storage_properties` + `storage_units_properties`. Subsequent standards review tightened the AGENTS Verification wording so the section no longer overstates CI (see Standards finding 1).

Scope: none. The `etl/db_utils.py` change is a docstring fix ("when they land" → storages landed under ADR 0006), faithful to the sweep and required for the AC4 claim to be defensible — not scope creep. Spec's raw/Service segment kept to the AC list; not a single extra sale.

---

Verdict: **The sweep makes every live doc read truthfully today and the standards fixes closed the fabricated-CI and the load-guard claims.** Remaining open item (tracked, not silently dropped): the load-if-not-exists guard remains unimplemented — this is a *code* gap for a future ticket, and both ADRs now say so explicitly.