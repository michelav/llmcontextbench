# Comparing experiment scenarios

Use one experiment file and one output root per scenario. This keeps each
`manifest.json`, trial snapshot, and derived result tied to its input settings.
Copy an existing experiment, then edit:

- `factors.model` and `factors.configuration` to choose comparable model and
  provisioning arms;
- `configurations` and `surfaces` to define each concrete treatment;
- `scope.instances` and `scope.tasks` to hold the request population constant;
- `execution.repeats` to set repetitions consistently;
- scenario-specific settings required by the dataset adapter and experimental
  treatment.

`llmctxbench execute` executes the configurations declared in the experiment file.
It does not perform per-request adaptive selection. Adaptive policy and runtime
code is maintained under `src/ctxbench/adaptive/`; use the
[provider-free validation guide](validation-guide.md) to inspect lifecycle behavior.

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

For a scenario experiment, allocate a fresh output directory such as
`runs/scenario`, then run:

```bash
llmctxbench plan path/to/experiment.json --output runs/scenario
llmctxbench status runs/scenario
llmctxbench execute runs/scenario/trials.jsonl
llmctxbench eval runs/scenario/responses.jsonl
llmctxbench export runs/scenario/evals.jsonl \
  --output runs/scenario/results.csv
llmctxbench metrics runs/scenario
```

Repeat the lifecycle with a separate experiment and output directory for each
comparison arm, for example `runs/arm-one` and `runs/arm-two`.
Keep dataset snapshot, scope, model, evaluation settings, and repeat count
identical unless that item is the scenario treatment. Review `status` and the
manifest before execution. `execute` and `eval` can invoke configured providers
and may incur cost.

The scenario files should declare their own `factors`, `configurations`,
`surfaces`, `scope`, and `execution.repeats`; do not rely on changing CLI
selectors to define an undocumented treatment. For adaptive policies, preserve the
standard benchmark artifacts and version any additional decision sidecars. Test
deterministic selection and recovery behavior with provider-free fixtures.
