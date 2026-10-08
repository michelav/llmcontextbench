# Worklog

- A completed and committed as 0a4109f. Split/count/hash/order checks and existing
  policy tests passed (64 tests). No providers used. Development token usage unavailable.
- B/C implementation: durable atomic request packets, canonical projections,
  replay from calibration, lock and explicit uncertain retry. Focused verification in progress.
- B completed as 3a45c25: all 20 runner/recovery tests passed; canonical artifacts
  accepted across all four arms and both scenarios. No evaluator or provider calls.
- C completed: dataset/config/source fingerprints, strict recovered treatment and
  observation validation, lifecycle reconciliation and original decision overhead
  preservation. 13 focused interruption/recovery tests passed.
- D completed: research entry point, local-MCP decorator, calibrated/frozen delay
  selection, nearest-rank quantiles, provider opt-in, byte/tokenizer budgets and
  cache scope/counterbalanced ordering. 33 focused tests passed. Preparation built
  320 paired candidates without credentials. Real scorer smoke passed (best_match,
  similarity 1.0) after repairing an ignored venv interpreter symlink; no dependency
  installation or lockfile changes. No paid calibration or study was run.
- E completed: canonical request/response/evaluation/trace joins, all-request quality
  denominators and metric coverage, reaction censoring, paired language-stratified
  target bootstrap, uninterrupted comparison-block sensitivity, CSV/JSONL and SVG
  timelines. Known partial/extra usage is accounted separately from unavailable totals.
- Final audit: 159 tests passed across adaptive runner/policy/calibration/analysis,
  RepoQA surfaces/scoring, runtime and canonical artifact contracts. All eight full
  arm/scenario interruption/resume comparisons matched deterministic fresh decisions
  and observations. Compileall and git diff --check passed. No providers used.
- Audit refinements: reject reused trial IDs, missing lifecycle histories, conflicting
  manifests and mismatched comparison/calibration provenance; preserve estimated
  serialization and multi-call token accounting provenance. Cache order balanced
  across six seed/scenario blocks. Canonical schemas and policy version remain fixed.
- All implementation slices complete. Paid calibration and held-out study remain
  separately authorized work, not unfinished implementation.

- CLI authorization follow-up (2026-10-08): accepted user plan removes the
  `--execute-providers` parser option and execution gate in one slice, retaining
  the informational cost notice, projections, scorer checks, frozen provenance,
  fingerprints, locking and `--retry-uncertain`. No artifact/schema or policy changes.
  Updated runner, workflow docs and stubbed CLI regression tests. Removed options
  fail parsing; changed source fingerprints require original-revision continuation
  or fresh preparation. Suggested commit: fix: remove RepoQA CLI authorization gate.
- Follow-up validation: `pytest -q tests/test_adaptive_calibration.py
  tests/test_adaptive_runner.py` passed all 41 tests; `git diff --check` passed.
  CLI execution/scoring were stubbed; no paid calls or dependency installs.
