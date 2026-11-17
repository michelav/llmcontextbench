# Adaptive experiments

An adaptive experiment runs an ordered workload of requests. For each request a **policy**
selects one **candidate** (a model plus a provisioning configuration) from a fixed catalogue.
The policy never sees the request — not its task, instance, size or labels. It sees only what
earlier requests showed: windowed readings of signals such as token usage, latency and failures.
Each request gets one decision and is executed once; there is no retry and no fallback.

The field reference is in [adaptive definition](reference/definition-adaptive.md); the design is
in [the adaptive workflow](../architecture/workflows/adaptive.md).

## Examples

| File | Shows |
|---|---|
| `examples/adaptive/minimal.json` | One request, one candidate, the `static` policy. |
| `examples/adaptive/window-threshold.json` | A generated workload, two candidates, a token budget per block of requests, a goal and a disturbance. |
| `examples/adaptive/code_built.py` | The same kind of experiment built in Python ([experiments in code](experiments-in-code.md)). |

All use the mock provider and `examples/datasets/fake`.

## Plan, execute, inspect

```console
llmctxbench plan examples/adaptive/minimal.json --output outputs/adaptive-minimal
llmctxbench status outputs/adaptive-minimal
llmctxbench execute outputs/adaptive-minimal/adaptive-plan.json
llmctxbench status outputs/adaptive-minimal
llmctxbench metrics outputs/adaptive-minimal
```

The run directory holds the frozen `adaptive-plan.json`, one record per request under
`adaptive-records/`, one record per attempt under `execution-records/`, and `responses.jsonl`
with one row per delivered request. See [output artifacts](reference/output-artifacts.md).

## A budget per block of requests

`window-threshold.json` declares two candidates over the same mock model:

```json
"candidates": {
  "json":   {"model": "mock", "configuration": "inline-json"},
  "blocks": {"model": "mock", "configuration": "inline-blocks"}
}
```

and a `window_threshold` policy that spends at most half of a 50-token budget per block of
four requests on `json`, then switches to `blocks` until the block ends:

```json
"policy": {"ref": "window_threshold", "params": {
  "signal": "total_tokens", "statistic": "sum",
  "window": {"requests": 4, "mode": "fixed"}, "capacity": 50,
  "tiers": [{"upTo": 0.5, "select": "json"}],
  "otherwise": "blocks", "when_unavailable": "blocks"}}
```

```console
llmctxbench plan examples/adaptive/window-threshold.json --output outputs/adaptive-budget
llmctxbench execute outputs/adaptive-budget/adaptive-plan.json
llmctxbench metrics outputs/adaptive-budget
```

Each request record shows the decision and why:

```text
sequence  candidate  reason
1         json       total_tokens.sum=0 capacity=50 utilisation=0 tier=1
2         json       total_tokens.sum=20 capacity=50 utilisation=0.4 tier=1
3         blocks     total_tokens.sum=40 capacity=50 utilisation=0.8 tier=otherwise
4         blocks     total_tokens.sum=61 capacity=50 utilisation=1.22 tier=otherwise
5         json       total_tokens.sum=0 capacity=50 utilisation=0 tier=1
```

The fixed window resets every four requests. The policy cannot know the cost of the next
request, so the block can still overshoot; the goal `tokens-per-block` (`sum` ≤ 60 per fixed
window of 4) reports it as `violated` in `metrics/adaptive_goal_metrics.csv`. Goals are reported,
never enforced. The `slow-model` disturbance adds 20 ms to every model call of requests 5–8; each
attempt records it under `disturbances` and the attempt metrics report it as `injectedDelayMs`.

## Policies

| `ref` | Use |
|---|---|
| `static` | Always one candidate (`candidate`). A baseline. |
| `random` | Seeded uniform choice, optionally over a subset (`candidates`). |
| `round_robin` | Cycle through the catalogue or a given order (`candidates`). |
| `window_threshold` | Tiers on one windowed reading, optionally against a `capacity`. |
| `min_signal` | Per candidate, the lowest (or highest, `objective: "max"`) windowed reading; explores candidates with fewer than `min_samples` observations first. |

Parameters are listed in [adaptive definition](reference/definition-adaptive.md#policy). Every
candidate ID a built-in policy names is checked at `plan`.

**Your own policy.** Reference a class as `"ref": "package.module:ClassName"`. The class has
`id` and `version` class attributes, takes its parameters as keyword arguments, and implements
`decide(candidates, state) -> Decision`:

```python
from ctxbench.api import Decision


class CheapestFirst:
    id = "cheapest_first"
    version = "1"

    def __init__(self, *, signal="total_tokens"):
        self.signal = signal

    def decide(self, candidates, state):
        readings = {c.candidate_id: state.window(self.signal, "mean", scope=f"candidate:{c.candidate_id}")
                    for c in candidates}
        untried = [c for c in candidates if readings[c.candidate_id].value is None]
        if untried:
            return Decision(untried[0].candidate_id, "explore")
        best = min(candidates, key=lambda c: readings[c.candidate_id].value)
        return Decision(best.candidate_id, f"lowest mean {self.signal}")
```

Rules: use only `state` and `state.rng()` — no clock, files, network or global state; keep memory
in the returned `memo`, not in instance attributes; return a non-empty reason. The policy's
source is fingerprinted at `plan`, and `execute` refuses a changed file. Make the module
importable, or pass its directory with `--plugin-path` to both `plan` and `execute`.

## Signals, windows and readings

Built-in signals: `latency_ms`, `total_tokens`, `input_tokens`, `output_tokens`,
`cached_input_tokens`, `reasoning_tokens`, `model_calls`, `tool_calls`, `failed`, `accepted`,
and `failed.<category>` for the failure categories `context_overflow`, `rate_limited`,
`provider_error`, `tool_error`, `step_limit`, `empty_response`, `capability_unavailable`,
`unknown`. Quality signals `quality.<metric>` come from online assessors declared in `signals`.

A reading aggregates one signal over a window (`{"requests": N}` sliding, `{"requests": N,
"mode": "fixed"}` per block, or `{"all": true}`) and a scope (`system` or
`candidate:<id>`) with a statistic (`sum`, `mean`, `median`, `min`, `max`, `last`, `p<q>`,
`rate`, `count`). A value the provider did not report is unavailable, never zero; a `sum` with
any unavailable value is unavailable.

## Online assessors

A quality signal is declared as `{"id": "quality.<metric>", "assessor": "<ref>"}`, where the
reference is an assessor the dataset provides or an external `module:Class`. Assessors run inside
the attempt, only for successful attempts, and their usage is reported separately from
generation usage. An assessor that uses reference data marks the run `privileged`: its results
cannot be presented as deployable behaviour.

## Resume

Running `execute` again resumes an interrupted run. Completed requests are replayed from their
records, recorded decisions are never recomputed, and an attempt that may have reached the
provider without a recorded result is retried only with `--retry-uncertain`. `--force` and
selectors are rejected for adaptive runs. To repeat an experiment, plan it again into a new
directory.

## Comparing runs

`ctxbench.api.summarize(runs, signals=[...])` returns one row per run (labels, policy, seed,
workload digest, counts, per-signal totals over all attempts and over delivered requests, goal
violations). Two runs are comparable request by request only when their workload digests are
equal. `ctxbench.api.headroom(...)` compares the best static candidate with a per-request oracle
over a benchmark matrix. Pairing and statistics are left to your scripts.
