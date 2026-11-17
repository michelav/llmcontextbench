# Concepts

LLMContextBench compares **context provisioning strategies**: ways of giving a model the context
it needs to answer a task. The dataset instances and tasks stay fixed; how the model receives or
retrieves context varies. The tool records responses, usage, timing, tool calls, traces,
evaluations and judge votes so runs can be inspected and reproduced.

## Datasets, instances and tasks

- A **dataset** is a versioned package of inputs (`tasks.json`, `tasks.instance.json`,
  `context/<instanceId>/…`, optionally `ctxbench.dataset.json`). See
  [creating a dataset](datasets/creating-a-dataset.md) and
  [using external datasets](datasets/using-external-datasets.md).
- An **instance** is one dataset unit: a curriculum, a repository, a document.
- A **task** is what the model must do over an instance: a question, an extraction, a summary.

## Models, surfaces, configurations

- A **model** is a provider plus a model name and parameters (`mock` needs no network).
- A **surface** selects context: `full_context`, or `operations` (an explicit list of
  adapter-owned tool operations).
- A **configuration** is a named treatment: a strategy, a representation and a surface.
- The **representation** names the context form the dataset adapter serves (for example `json`
  or `blocks`).

## Strategies

| Strategy | How the model gets context |
|---|---|
| `inline` | The selected representation is inserted into the prompt. |
| `local_function` | The tool exposes local functions and runs the tool loop. |
| `local_mcp` | The tool exposes a local MCP runtime and runs the loop. |
| `remote_mcp` | A remote MCP server provides context; provider-side behaviour may be less observable. |

When a strategy cannot expose a value reliably, the value is recorded as unavailable, not zero.

## Two workflows

- **Benchmark.** A static matrix: every trial (task × instance × model × configuration ×
  repeat) is fixed at plan time. Use it to measure each configuration on the same inputs.
  See [benchmark experiments](benchmark-experiments.md).
- **Adaptive.** An ordered workload of requests and a catalogue of candidates (model plus
  configuration). For each request a **policy** picks one candidate using only observations of
  earlier requests — it never sees the request itself. Use it to study how a system adapts to
  what it observes. See [adaptive experiments](adaptive-experiments.md).

Both share the lifecycle `plan → execute → eval → export / metrics / status`.

## Phases and costs

- `plan` freezes the run and never calls a provider.
- `execute` is the only phase that runs answer generation.
- `eval` is the only phase that runs judge models.
- `export`, `metrics` and `status` read artifacts only.

Generation usage, online assessor usage (adaptive) and judge usage are recorded and reported
separately.

## Provenance of values

Every metric value is `reported` (by a provider), `measured` (by the tool), `derived`
(computed from those), `estimated` (approximated) or `unavailable`. See
[metrics](reference/metrics.md).
