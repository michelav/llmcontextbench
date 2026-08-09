# Create lightweight spec

Use this with `/speckit.specify` when you want to register intent, scope, dependencies, and non-goals without planning implementation yet.

```text
/speckit.specify

Do not create or switch branches.
Do not implement code.
Do not run provider-backed commands.

SPECIFY_FEATURE_DIRECTORY={{SPEC_DIR}}

Create a lightweight specification named "{{SPEC_NAME}}".

This is an early roadmap-level specification. The goal is to define intent, scope,
dependencies, acceptance criteria, and non-goals. Do not over-detail implementation.

Goal:

Define target artifact contracts and migration behavior for LLMContextBench.

The spec must distinguish:

- canonical artifacts;
- derived artifacts;
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

The spec must define whether readers support legacy artifacts, whether writers produce only target artifacts, and how migration is documented.

The spec must also define how metric provenance is represented using the simplest sufficient model: reported, measured, derived, estimated, unavailable.

Do not introduce a new domain in this spec.
Do not run provider-backed commands.

{{FEATURE_GOAL}}

The spec must clarify:

- what this change is trying to achieve;
- why it is needed;
- what is in scope;
- what is explicitly out of scope;
- which existing concepts, contracts, artifacts, or docs may be affected;
- which previous specs it depends on;
- which future specs it enables;
- which decisions should be deferred until planning.

Dependencies:

{{DEPENDENCIES}}

Enables:

{{ENABLED_SPECS}}

The spec must preserve:

- phase separation;
- artifact contracts;
- metric provenance;
- strategy comparability;
- domain/provider boundary isolation;
- reproducibility and traceability;
- simplicity and research sufficiency.

Focus on WHAT and WHY. Avoid implementation details.
```
