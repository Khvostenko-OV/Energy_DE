# Code review — incremental collision links on close partners (issue #30)

- **Date:** 2026-09-22
- **Fixed point:** `HEAD` — uncommitted/staged work under review
- **Diff:** `git diff HEAD` — 1 file, 81 insertions, 11 deletions
- **Commits:** none (working tree, pre-commit)
- **Reviewed artifacts:** `etl/load.py` — `_close_location_pairs` extracted from `_detect_close_location`; new `_rows_referencing_ids_in_close_to` + `_expand_collision_affected`; `_load` feeds the expanded close-location component to `_reset_collision_annotation` and `_detect_collisions` (property transfer keeps the original `affected` set)
- **Spec source:** GitHub issue #30

## Standards

### Hard violations (documented standards)

None. Verified against the diff:

- **AGENTS.md / spec vocabulary** — names stay on the collision/close-pair/affected vocabulary; `close_to` lives in `secondary_attributes` JSON, matching the de-facto internal convention already used by `_write_close_locations` and the reset scrub. Spec algorithm preserved: close-pair join stays "10 m, only geo_accuracy=1" (`TechnicalSpecification.md:78`).
- **No linters/typecheckers** (AGENTS.md) — nothing tool-enforced; one added line initially ran 91 chars and was wrapped to match the file's multi-line call style.

### Judgement calls (baseline smells)

**Possible Duplicated Code — JSON-cast idiom.** `_rows_referencing_ids_in_close_to` (the `secondary_attributes::jsonb ? 'close_to'` + `jsonb_array_elements(...)` + `(elem #>> '{}')::int = ANY(:ids)` shape) repeats the element-cast predicate already present in `_reset_collision_annotation`'s scrub query. They live in two structurally different SQL contexts (a `SELECT … WHERE EXISTS` vs an `UPDATE … FROM (SELECT … jsonb_agg)`), so factoring a shared SQL fragment was judged to buy more indirection than it removes — left as-is.

**Mysterious Name — addresses.** `_rows_referencing_in_close_to` was renamed `_rows_referencing_ids_in_close_to` with the parameter renamed `ids` (it is tested against the *grown* expansion set, not just the original affected rows), so the name now says exactly what the membership test is.

**Fixpoint loop shape.** `_expand_collision_affected` re-issues the pair join and the referrer query (and re-sorts) per fixed-point iteration; a recursive SQL closure could express the component in one statement, but the loop reuses the exact query `_detect_close_location` runs, keeping one source of truth for the pair definition. Logically sound.

## Spec

Verified against issue #30. No missing requirements, no material scope creep.

- **(a) Missing/partial** — none. The chosen direction ("also treat a row as 'affected' when one of its close-pair partners changed — recompute the pair both ways") is implemented via component expansion; both named repro tests pass and the stated invariants hold (253/253 links, 249/249 close_to on the issue's own units 23/24/25/27 around unit 26). Direction 3 (fingerprint-based link table) is an explicit "or" alternative, not composite.
- **(b) Scope creep** — none. `_close_location_pairs` extraction is the seam the expansion loop needs. Transitive component expansion (vs the issue's literal "close-pair partners") is justified: with one-hop partners only, a partner-of-partner re-flagged by `_detect_close_location` but untouched by the reset would gain the very same class of second, reason-incomplete link the issue describes.
- **(c) Implemented wrong** — none, with one acknowledged limitation. The moved-away-partner case is handled from a *consistent* prior state (B's `close_to` still names A, so `_rows_referencing_ids_in_close_to` sweeps it in). It does **not self-heal** a database the old bug already corrupted — if a prior buggy run scrubbed B's `close_to` and left the stale link, no geometric pair and no `close_to` reference survives to rediscover B. That corruption is loudly surfaced by the load verifier (collision-link/reason checks) rather than silently patched; repairing already-corrupted DBs is a migration beyond the issue's scope and is called out here as the one residual.

Summary: Standards — 0 hard findings, 3 documented judgement calls (worst: the duplicated JSON-cast idiom, deliberately not factored). Spec — 0 findings; implementation matches the issue's suggested direction and all repro invariants, with the acknowledged no-self-heal-on-pre-corrupted-DB limitation flagged.

Reviewed per the code-review skill; report saved to `docs/reviews/code-review-incremental-collision-links-20260922.md`.