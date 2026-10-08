# Comparing experiment scenarios

Use one experiment file and one output root per scenario. This keeps each
`manifest.json`, trial snapshot, and derived result tied to its input settings.
Copy an existing experiment, then edit:

- `factors.model` and `factors.configuration` to choose comparable model and
  provisioning arms;
- `configurations` and `surfaces` to define each concrete treatment;
- `scope.instances` and `scope.tasks` to hold the request population constant;
- `execution.repeats` to set repetitions consistently;
- scenario-specific settings such as RepoQA `params` and controlled tool delay
  settings used by a research runner.

The standard CLI executes the configurations declared in the experiment file.
It does not perform per-request adaptive selection. Adaptive policies and
latency-injection scenarios use `tools/repoqa/run_adaptation.py`; see the
[resumable workflow](repoqa-resumable-workflow.md) for preparation, calibration,
freezing, resume and analysis.

## Provider-free CLI smoke check

The checked-in fake dataset experiment uses a mock model and disables evaluation.
Planning and status inspection require no model provider:

```bash
llmctxbench plan tests/fixtures/fake_dataset/experiment.json \
  --output /tmp/ctxbench-fake-smoke
llmctxbench status /tmp/ctxbench-fake-smoke
```

This checks dataset resolution and trial generation. It intentionally stops
before `execute` because this fixture is a planning smoke check, not a
provider-backed execution test.

## Standard scenario lifecycle

For a scenario experiment at `experiments/repoqa-control.json`, allocate a
fresh directory such as `runs/repoqa-control`, then run:

```bash
llmctxbench plan experiments/repoqa-control.json --output runs/repoqa-control
llmctxbench status runs/repoqa-control
llmctxbench execute runs/repoqa-control/trials.jsonl
llmctxbench eval runs/repoqa-control/responses.jsonl
llmctxbench export runs/repoqa-control/evals.jsonl \
  --output runs/repoqa-control/results.csv
llmctxbench metrics runs/repoqa-control
```

Repeat the lifecycle with a separate experiment and output directory for each
comparison arm, for example `runs/repoqa-inline` and `runs/repoqa-local-mcp`.
Keep dataset snapshot, scope, model, evaluation settings, and repeat count
identical unless that item is the scenario treatment. Review `status` and the
manifest before execution. `execute` and `eval` can invoke configured providers
and may incur cost.

The scenario files should declare their own `factors`, `configurations`,
`surfaces`, `scope`, and `execution.repeats`; do not rely on changing CLI
selectors to define an undocumented treatment. For an adaptive experiment,
plan the complete candidate catalog as required by the research runner, then
give each policy, seed, and scenario its own output root. Canonical artifacts
remain the standard CLI artifacts; policy decisions belong in the runner's
versioned sidecar as specified by the prototype.

## Adaptive episode recovery

Use `--resume` on the research runner, including calibration operations. An uncertain
provider attempt additionally requires `--retry-uncertain`; prior cost stays unavailable.
Evaluate only completed episodes. The [protocol](repoqa-resumable-workflow.md) defines
fingerprints, atomic packets, paired schedules and interrupted-block sensitivity.
