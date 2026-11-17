# Output artifacts

Each run lives in one directory (`<output>/<id>/` or `plan --output`). JSON and JSONL records
are canonical; CSV files and `responses.jsonl` are rebuilt from them. Field-level contracts:
[artifacts](../../architecture/contracts/artifacts.md),
[manifests](../../architecture/contracts/manifest.md),
[adaptive plan](../../architecture/contracts/adaptive-plan.md),
[records](../../architecture/contracts/records.md).

## Benchmark run

```text
<run>/
├── manifest.json          versions, dataset provenance, execution fingerprint
├── resolved.json          the resolved definition
├── trials.jsonl           one frozen trial per line
├── execution-records/     one record per execution attempt (authoritative)
├── responses.jsonl        one response per trial, rebuilt from execution records
├── evals.jsonl            aggregated evaluation per response (after eval)
├── judge_votes.jsonl      one vote per judge and response (after eval)
├── evals-summary.json     evaluation summary (not used by metrics)
├── results.csv            export
├── metrics/               metric tables
└── traces/
    ├── executions/<trialId>.json
    └── evals/<trialId>.json
```

## Adaptive run

```text
<run>/
├── manifest.json                 versions, dataset, labels, seed, privileged, mixedModels, fingerprint
├── resolved.json                 the resolved definition (not hashed)
├── adaptive-plan.json            the frozen plan; its SHA-256 is the execution fingerprint
├── adaptive-records/<requestId>.json   decision, observation and delivery per request
├── adaptive-lifecycle.json       execution sessions
├── execution-records/            one record per execution attempt
├── responses.jsonl               one row per delivered request
├── evals.jsonl, judge_votes.jsonl   offline evaluation of delivered responses (after eval)
├── metrics/                      adaptive_request_metrics.csv, adaptive_attempt_metrics.csv,
│                                 adaptive_goal_metrics.csv, metrics-manifest.json
└── traces/
```

A failed adaptive request has no row in `responses.jsonl`; its attempt and failure category are
in its request record and in the attempt metrics.

## Rules

- Every attempt has its own record file. A completed attempt is replayed on resume, never
  re-invoked.
- `export`, `metrics` and `status` read artifacts only and never call providers.
- Unavailable values are empty or `null`, never zero.
- Older artifact versions are rejected; plan a fresh run. There is no migration.
