# Implementation slices

A: `adapters/repoqa/study.py`, dedicated experiment and workload tests. Deterministic
split/hash/order, strict pairing, measured bytes, actual initial prompt budgets.
Risk: wrong variants/budgets. Commit: feat: prepare reproducible RepoQA adaptive workloads.

B: adaptive runner/recovery helpers and integration tests. Durable packet first;
canonical artifacts projected atomically. Independent policy state and measured
outer execution duration. Depends on A. Risk: multi-file durability.
Commit: feat: execute and persist adaptive RepoQA episodes.

C: replay/fingerprint/locking/uncertain attempt validation and interruption tests.
Same unit recovery for fixed calibration episodes. Depends on B. Risk: duplicate
provider expenditure and changed external conditions during downtime.
Commit: feat: resume adaptive RepoQA episodes from saved history.

D: optional executor decorator, disturbance/calibration functions, research CLI.
Freeze provenance and explicit provider opt-in; dependency-free preparation.
Depends on C. Risk: no qualifying latency disturbance.
Commit: feat: calibrate controlled RepoQA adaptation scenarios.

E: saved-episode analysis, synthetic checks and protocol docs. Coverage and resource
uncertainty, paired language-stratified bootstrap and interruption sensitivity.
Depends on D. Risk: interrupted runs restore state but not provider conditions.
Commit: feat: analyze resumable RepoQA adaptation episodes.

Focused tests per slice; no paid execution. Relevant source fingerprint includes
uncommitted changes. Canonical provisioning version 2 remains untouched.
