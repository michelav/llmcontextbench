# Benchmark definition (`schemaVersion: 3`)

A benchmark definition is a JSON object validated by
`ctxbench.benchmark.definitions.definition_schema()`. Unknown top-level fields are rejected.
Example: `examples/benchmark/static-minimal.json`.

```json
{
  "schemaVersion": 3,
  "kind": "benchmark",
  "id": "my-benchmark",
  "dataset": {"root": "../datasets/fake"},
  "models": {"mock": {"provider": "mock", "name": "mock", "modelParams": {}}},
  "surfaces": {"full": {"type": "full_context"}},
  "configurations": {"inline": {"strategy": "inline", "representation": "json", "surface": "full"}},
  "candidates": [["mock", "inline"]],
  "execution": {"repeats": 1},
  "evaluation": {"enabled": false}
}
```

| Field | Required | Content |
|---|---|---|
| `schemaVersion` | yes | `3`. |
| `kind` | no | `"benchmark"` (the default). |
| `id` | yes | Experiment ID; also the default output subdirectory. |
| `name`, `output` | no | Display name; output root (default `outputs`, overridden by `plan --output`). |
| `extends` | no | Path of a parent definition, merged before validation (single parent). |
| `dataset` | yes | `{"root": "<path>"}` for a local dataset (relative to the definition), `{"id": "<id>", "version": "<version>"}` for a cached one, or a reference string. |
| `scope` | no | `{"instances": [...], "tasks": [...]}` to restrict the matrix; empty means all. |
| `models` | yes | Map of model key to `{"provider", "name", "modelParams"}`. Providers: `mock`, `openai`, `claude`, `gemini`. `modelParams` may include a `rate_limit` block for client-side throttling and retries. |
| `surfaces` | yes | Map of surface key to `{"type": "full_context"}` or `{"type": "operations", "operations": [...]}`. |
| `configurations` | yes | Map of configuration ID (`^[a-z][a-z0-9_.-]*$`) to `{"strategy", "representation", "surface"}`; strategy is `inline`, `local_function`, `local_mcp` or `remote_mcp`. |
| `candidates` | yes | List of `[modelKey, configurationId]` pairs to run. |
| `taskParams`, `modelParams` | no | Parameters for task templates and default model parameters. |
| `execution` | no | `{"repeats": N, "options": {...}}`. |
| `evaluation` | no | `{"enabled": bool, "judges": [{"provider", "model", "temperature", "params"}], "config": {...}}`. |
| `trace` | no | `{"enabled", "writeFiles", "save_raw_response", "save_tool_calls", "save_usage", "save_errors"}`. |
| `artifacts` | no | `{"writeJsonl", "writeIndividualJson"}`. |

The trial matrix is `scope.tasks × scope.instances × candidates × repeats`. Older schema
versions are rejected; there is no migration.
