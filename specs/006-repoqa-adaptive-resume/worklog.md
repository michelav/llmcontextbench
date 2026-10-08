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
