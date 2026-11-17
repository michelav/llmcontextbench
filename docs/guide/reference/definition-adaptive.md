# Adaptive definition (`schemaVersion: 4`)

An adaptive definition is a JSON object validated by
`ctxbench.adaptive.definition.adaptive_definition_schema()`. Unknown fields are rejected at every
level. Examples: `examples/adaptive/minimal.json`, `examples/adaptive/window-threshold.json`. The
same sections can be built in Python ([experiments in code](../experiments-in-code.md)).

## Top level

| Field | Required | Content |
|---|---|---|
| `workflowKind` | yes | `"adaptive"`. |
| `schemaVersion` | yes | `4`. |
| `id` | yes | Experiment ID. |
| `output` | no | Output root (default `outputs`; overridden by `plan --output`). |
| `seed` | no | Integer run seed (default `0`); seeds the policy's random source. |
| `labels` | no | String map copied to the manifest and metric rows (for example the study arm). |
| `extends` | no | Path of a parent definition, merged before validation. |
| `dataset` | yes | `{"root": "<path>"}` (relative to the definition), `{"id", "version"}`, optional `origin`, or a reference string. |
| `models` | yes | Map of model key to `{"provider", "name", "modelParams"}`, as in the [benchmark definition](definition-benchmark.md). |
| `surfaces` | yes | Map of surface key to `{"type": "full_context"}` or `{"type": "operations", "operations": [...]}`. |
| `configurations` | yes | Map of configuration key to `{"strategy", "representation", "surface"}`. |
| `candidates` | yes | Map of candidate ID to `{"model": <model key>, "configuration": <configuration key>, "labels": {}}`. Declared order is the catalogue order. |
| `allowMixedModels` | no | `true` to allow candidates with different models (default `false`). |
| `taskParams` | no | Parameters for task templates. |
| `execution` | no | `{"options": {...}}`. |
| `workload` | yes | [Workload](#workload). |
| `policy` | yes | [Policy](#policy). |
| `window` | yes | Default window for readings and goals: `{"requests": N}`, `{"requests": N, "mode": "fixed"}` or `{"all": true}`. |
| `signals` | no | [Online assessors](#signals). |
| `acceptance` | no | `{"minimumResponseLength": N}` (default `0`): a successful response shorter than `N` characters fails the request. |
| `goals` | no | [Goals](#goals). |
| `disturbances` | no | [Disturbances](#disturbances). |
| `evaluation` | no | Offline evaluation, as in the benchmark definition. |
| `trace` | no | Trace settings. |

All candidates must reference one model unless `allowMixedModels` is `true`. Every candidate's
strategy must be supported by the dataset.

## Workload

Explicit, in order:

```json
"workload": {"requests": [
  {"requestId": "r-0001", "taskId": "task_role", "instanceId": "person-001", "labels": {}}
]}
```

`requestId` is optional (generated as `r-000001`, … from the position when omitted; generated workloads use `r-0001`, …). The same task and instance may
appear many times.

Generated:

```json
"workload": {"generator": {
  "seed": 7,
  "tasks": [], "instances": [],
  "sampling": "with_replacement",
  "segments": [{"size": 10}, {"size": 10, "where": {"<feature>": "<value>"}}],
  "labelFeatures": ["<feature>"]
}}
```

The pool is the cross product of the selected tasks and instances (empty lists mean all).
Each segment draws `size` requests, optionally filtered by declared request features (`where`:
equality, or `{"min", "max"}` for numeric features). `sampling` is `with_replacement` or
`without_replacement` (which fails when a segment needs more than its pool). `labelFeatures`
copies feature values into request labels. The draw depends only on the seed, the segment index
and the sorted pool.

## Policy

```json
"policy": {"ref": "<name or module:Class>", "params": {...}, "sources": ["<extra file>"]}
```

`sources` (optional) lists extra files covered by the policy's source digest, relative to the
definition.

| `ref` | Parameters |
|---|---|
| `static` | `candidate` (required). |
| `random` | `candidates` (optional subset). |
| `round_robin` | `candidates` (optional order). |
| `window_threshold` | `signal`, `statistic`, `tiers` (non-empty list of `{"upTo": number, "select": candidate}` with strictly ascending `upTo`), `otherwise`, `when_unavailable` (required); `scope` (default `system`), `window` (default: the experiment window), `capacity` (positive; makes `upTo` a fraction of it), `min_samples` (default `1`; not applied to `sum` and `count`). |
| `min_signal` | `signal`, `statistic` (required); `window`, `objective` (`min` or `max`, default `min`), `min_samples` (default `1`; at least `2` for a percentile). |

Signals: `latency_ms`, `total_tokens`, `input_tokens`, `output_tokens`, `cached_input_tokens`,
`reasoning_tokens`, `model_calls`, `tool_calls`, `failed`, `accepted`, `failed.<category>`, and
declared `quality.<metric>` signals. Statistics: `sum`, `mean`, `median`, `min`, `max`, `last`,
`p<q>` (for example `p95`), `rate` (0/1 signals only), `count`. Scopes: `system`,
`candidate:<id>`.

## Signals

```json
"signals": [{"id": "quality.<metric>", "assessor": "<dataset signal ID or module:Class>", "sources": []}]
```

Each declared signal is produced by an online assessor that runs after each successful attempt.
An assessor that uses reference data marks the run `privileged`.

## Goals

```json
"goals": [{"id": "latency", "signal": "latency_ms", "statistic": "p95", "upper": 5000,
           "scope": "system", "window": {"requests": 10}}]
```

Exactly one of `upper` and `lower`. `scope` defaults to `system`, `window` to the experiment
window. Goals are evaluated by `metrics`, never enforced.

## Disturbances

```json
"disturbances": [{"name": "slow-model", "version": "1", "component": "model", "kind": "delay",
                  "delayMs": 20, "firstSequence": 5, "lastSequence": 8, "seed": 1, "candidates": []}]
```

| Field | Content |
|---|---|
| `name`, `version` | Required; names are unique. |
| `component` | `model`, `local_function`, `local_mcp` or `remote_mcp`. |
| `kind` | `delay` (needs `delayMs`), `failure` (needs `failureRate`), `delay_and_failure` (at least one). |
| `delayMs` | Integer milliseconds added to every call of the component. |
| `failureRate` | Probability in `[0, 1]` that each call fails. |
| `firstSequence`, `lastSequence` | Sequence range (default from 1 to the end). |
| `seed` | Seed of the failure draws (default `0`). |
| `candidates` | Candidates affected; empty means every candidate that uses the component. |

`plan` refuses disturbances that can never take effect.
