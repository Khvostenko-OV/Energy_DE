# Code review — Transform align to spec v2.2 (issue #11)

- **Date:** 2026-09-14
- **Fixed point:** `f45aa4e` (Tech Specification v2.2) — post-commit review of the committed diff
- **Diff:** `git diff f45aa4e...HEAD` — 11 files, 303 insertions / 35 deletions
- **Commits:** `0dbf961` feat (transform — align staging shape to spec v2.2), `16762c2` refactor (promote `_drop_whitelisted` to a module helper)
- **Reviewed artifacts:** staging `secondary_attributes` column (DDL + STAGING_COLUMNS), whitelist decomposition (`DECOMPOSED_PROPERTIES`, `_decompose_attributes`, `_safe_attributes`, `_drop_whitelisted`), region-null gate removal from `_quality_reasons`, verify whitelist-drift gates, integration test suite + pytest dev requirement, CONTEXT.md / ADR 0005 spec-v2.2 updates
- **Spec source:** GitHub issue #11 (fetched via `gh issue view 11`, state CLOSED), TechnicalSpecification.md (Transform/Staging), CONTEXT.md, ADR 0005
- **Standards sources:** AGENTS.md + CONTEXT.md + ADRs + TechnicalSpecification.md + prior review `code-review-transform-v22-20260914.md` + Fowler smell baseline (Refactoring ch.3)
- **Context:** implementation verified against live PostGIS (full integration suite, 14 tests, all sources transformed). The prior review of this work was of the uncommitted tree; this review covers the committed state incl. `16762c2`. Prior `[fixed]` items re-verified in HEAD: tests import `DECOMPOSED_PROPERTIES`, verify uses `?|` key membership, shared `_safe_attributes`, region-null gate removed.
- **Decisions locked with the user:** seams = full integration against dev DB; no typechecker; pytest requested up front (not creep).

Two-axis review: **Standards** (conformance + smells) and **Spec** (faithful implementation), deliberately kept separate.

---

## Standards

- **Duplicated Code — whitelist partition runs twice per row.** `_decompose_attributes` filters `if name in DECOMPOSED_PROPERTIES` (transform.py:292), then `_drop_whitelisted` re-parses the *same* json and filters the complement `if k not in DECOMPOSED_PROPERTIES` (transform.py:321), both via `_safe_attributes`. Two adjacent passes, complementary predicates. The two new verify drift-gates exist precisely because these passes can disagree — a six-line seam that one pass (emitting both `props` and the reduced dict) would remove. Judgement call.
- **Mysterious Name / fail-loudly tension — `_safe_attributes` (transform.py:258-270).** `except ValueError: return {}` and the non-dict `else {}` collapse corruption, non-object JSON, unparseable text, and an empty bag to the same `{}` — a malformed source payload silently becomes `"{}"` with zero trace, so verify's `leaked` gate (verify.py:250-258) can't see what was swallowed. verify.py is documented as fail-loudly checks; silently normalizing corruption cuts against that ethos. Robustness choice; worth recording, not a violation.
- **Duplicated Code (micro) + early Divergent Change — `_verify_transform` (verify.py).** `quoted_names` is built identically for both new checks; the two whitelist gates are a natural `_verify_whitelist(engine, source)` seam. The function now spans ten unrelated domains (rows, keys, labels, storage shape, quality, distribution, props, links, whitelist). Judgement call.
- **TEXT-vs-jsonb contract stays out-of-band.** DDL declares `secondary_attributes TEXT` (db_utils.py:65), matching the spec tables (`secondary_attributes | text`, TechnicalSpecification.md:136/153) — compliant. But the CONTEXT.md edited in this diff still calls it a "jsonb column", and verify.py:253 plus the tests cast `::jsonb`, so the TEXT contents' type-contract and validity are enforced only by those casts. Spec-vs-CONTEXT doc feud retained; same shape as the raw-side twin flagged in the extract review.
- **Test harness hair (tests/test_transform_v22.py:16).** `ENGINE = create_engine(os.environ["DATABASE_URL"])` at import time errors at collection, not per-test; the module-level `scalar` helper duplicates verify's nested one. Minor — both seams were user-agreed.
- **Not flagged:** pytest / requirements-dev.txt / verify invariants are user-requested, not creep; region-gate removal reachability is correct (`_coordinates_mismatch` leak noted in the issue, not in the code); no hard documented-standard violations.

## Spec

Reviewed against issue #11 + TechnicalSpecification.md + ADR 0005. The four issue requirements are implemented correctly end-to-end.

- **(a) Reconcile AC is partial.** "Quality histogram, decomposition counts, and verification reconcile against the previous transform for unchanged sources." The only mechanism is frozen literals (`EXPECTED_BAD_QUALITY`/`EXPECTED_REGION_NULLS`) measured from the old DB — internally consistent (51 region-null rows = the 63→12 bad drop), but an assertion, not a recomputed diff against the previous transform. The histogram itself is only checked via "no `region` in any bad_quality value".
- **(b) Scope creep — CONTEXT.md + ADR 0005 assert unbuilt behaviour.** CONTEXT.md states as fact that null-region units "are flagged `collision` … reported under the 'outside' bucket in the marts" and that core rows hold "the reduced `secondary_attributes` jsonb" — neither exists yet (load/core = #4/#6/#7/#9, out of scope). The spec-aligning docs describe a system this diff doesn't build.
- **(b) Two new verify drift-gates go beyond the letter** — AC says verification *reconcile*, not "add invariants". Justified by the repo's fail-loudly pattern; still a judged addition.
- **(b) Process noise** — the `docs/reviews/` snapshot and `.gitignore` `.pytest_cache/`. Tests/`requirements-dev.txt` were user-requested, not creep.
- **(c) Silent data-loss fallback.** `_decompose_attributes` and `_drop_whitelisted` share `_safe_attributes`, which coerces any malformed/non-object doc to `{}` — a corrupted raw doc hits staging as `secondary_attributes="{}"` with no verify signal, violating "containing exactly the non-whitelisted keys for every row"; the whitelist drift gates can't flag a key dropped before staging. Only extract's guarantee (valid `json.dumps`) makes it unreachable.
- **(c) verify message overstates.** The nonwhitelist check is `COUNT(*)` over property *rows* while reporting "N non-whitelisted **names** found" — one bad name used 10× reports 10.
- **(c) Pre-existing, unchanged:** decomposed values use `str(value)`, not a JSON round-trip (a nested dict becomes `"{'k': 1}"`).

**AC cross-check:** staging `secondary_attributes` on all six tables, exact 14-key whitelist incl. storage `technology`, both filters honoring it, region gate removed from `_quality_reasons` — present and enforced. The literal-only reconcile, doc overreach, and two low-severity robustness/message issues are the residuals.

---

## Summary

- **Standards — 5 findings, all judgement calls, none hard.** Worst: the two-pass whitelist partition (`_decompose_attributes` filter vs `_drop_whitelisted` complement) whose divergence is exactly what the new verify gates exist to catch.
- **Spec — 3 finding-groups.** Worst: the silent `_safe_attributes` coercion, which can break "exactly the non-whitelisted keys for every row" without any verify signal (only extract's guarantee makes it unreachable) — with the CONTEXT/ADR overreach asserting unbuilt load-side behaviour a close second.