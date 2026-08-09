# Create artifact contracts and migration spec

Use this with `/speckit.specify`.

```text
/speckit.specify

Do not create or switch branches.
Do not implement code.
Do not run provider-backed commands.

SPECIFY_FEATURE_DIRECTORY=specs/002-artifact-contracts-and-migration

Create a specification named "artifact-contracts-and-migration".

The goal is to define target artifact contracts and migration behavior for LLMContextBench.

The spec must distinguish:

- canonical artifacts;
- derived artifacts;
- planning artifacts;
- execution artifacts;
- evaluation artifacts;
- analysis-ready exports;
- traces;
- compatibility aliases for legacy artifacts.

Target artifact names include:

- `manifest.json`
- `trials.jsonl`
- `responses.jsonl`
- `evals.jsonl`
- `judge_votes.jsonl`
- `evals-summary.json`
- `results.csv`
- `traces/executions/<trialId>.json`
- `traces/evals/<trialId>.json`

Legacy names may include:

- `queries.jsonl`
- `answers.jsonl`
- `traces/queries/<runId>.json`

The spec must define whether readers support legacy artifacts, whether writers produce only
target artifacts, and how migration is documented.

The spec must also define how metric provenance is represented using the simplest sufficient
model: reported, measured, derived, estimated, unavailable.

Do not introduce a new domain in this spec.
Do not run provider-backed commands.
```
