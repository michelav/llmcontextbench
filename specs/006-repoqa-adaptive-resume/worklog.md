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
