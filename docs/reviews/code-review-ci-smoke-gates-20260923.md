# Code review — CI smoke gates (issue #14)

- **Date:** 2026-09-23
- **Fixed point:** `HEAD` (d7c06e6) — review of the uncommitted working tree (the work was committed after review)
- **Diff:** `git diff HEAD` + new untracked `.github/workflows/ci.yml`
- **Spec source:** GitHub issue #14 (fetched via `gh issue view 14`; blocker #13 CLOSED)
- **Reviewed artifacts:** `.github/workflows/ci.yml` (new), README Stack row, AGENTS.md Verification section, `docs/containerization.md` ticket list
- **Verification:** YAML parsed; `python -m compileall -q etl viz tests scripts docker` green; `docker build -t etl-pipeline:ci .` green; full pytest suite `327 passed`

## Standards

Two parallel-review findings:

1. **Hard — stale status docs.** The change ships #14 but README.md:30 ("GitHub Actions (CI, planned — #14)") and AGENTS.md:57 ("CI is planned (#14)") claimed it was unbuilt, and containerization.md:255 still said "blocked by #13". A single logical change (CI goes live) landed in only one of the three surviving status markers. **Fixed:** README Stack row references `.github/workflows/ci.yml` as the CI smoke gates; AGENTS Verification now describes the cheap gates (byte-compile + image build, no raw data, no integration suite); containerization.md ticket line updated (no longer blocked, lives in CI).

2. Judgeable smells, accepted deliberately:
   - **Redundant dependency install** — `pip install -r requirements.txt` is dead work for `compileall` (it never imports). Kept: AC 2 of #14 literally requires installing the runtime dependencies, so the spec overrides the smell.
   - **Version drift** — the compile job pins `python 3.12` while the image builds Chainguard 3.14; the two jobs gate complementary interpreters, and 3.12 matches the dev venv (byte-compile is interpreter-agnostic). Accepted.
   - **Static check vs "no linters/typecheckers"** — `compileall` is a byte-compile gate, neither a linter nor typechecker; AGENTS.md:51 wording stays true. Noted in AGENTS Verification.

Verified correct: YAML valid; `on:` key order and `pull_request:` null mapping correct; `'3.12'` quoted (avoids float-tag resolution); no extra triggers; no pytest step (suite needs private data); image build uses the repo-root `Dockerfile` with `.dockerignore` excluding `data/`.

## Spec

All four acceptance criteria addressed; no missing ACs, negligible creep, no incorrect behaviour:

| AC | Result |
|----|--------|
| A workflow runs on push to `main` and on pull requests | ✅ `on.push.branches: [main]` + `on.pull_request` |
| It installs the runtime dependencies and byte-compiles every module and test | ✅ `pip install -r requirements.txt`; `python -m compileall -q etl viz tests scripts docker` (the repo's five Python source trees, incl. `tests/`) |
| It builds the pipeline container image and the build is green | ✅ `docker build -t etl-pipeline:ci .` (repo-root `Dockerfile`, `.dockerignore` strips `data/`) — green locally |
| No raw data is fetched or required, and the integration suite does not run | ✅ no pytest step, no `DATABASE_URL` secret, no data mounts anywhere |

Deviations (signposted, accepted): `python-version: '3.12'` pins an interpreter the spec didn't name (matches the dev venv; harmless); two separate jobs are implementation freedom, each gating an invariant independently.

## Summary

Standards: 1 hard finding (stale status docs, fixed). Worst: the stale README/AGENTS status lines. Spec: 0 missing, 0 substantive creep, 0 look-wrong. The workflow meets all four #14 acceptance criteria and was verified by execution (compileall, image build, full suite).

**Post-review re-verification:** the doc fixes touch no Python, `python -m compileall` stays green, and `git status` shows only the intended files.