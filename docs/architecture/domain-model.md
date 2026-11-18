# Domain model

The vocabulary of the tool. Workflow contracts are in
[workflows/workflow-contract.md](workflows/workflow-contract.md); the adaptive domain diagram is
in [workflows/adaptive.md](workflows/adaptive.md#domain-model).

## Core terms

| Term | Meaning |
|---|---|
| `dataset` | Versioned package of benchmark inputs. |
| `dataset repository` | External source that publishes a dataset package or release asset. |
| `dataset package` | The dataset distribution envelope resolved by LLMContextBench. |
| `dataset materialization` | One locally materialized copy of a dataset package. |
| `dataset cache` | Local store of fetched dataset materializations and manifests. |
| `dataset resolver` | Local-only component that resolves `root` or `id@version` references. |
| `dataset capability report` | Read-only validation summary returned by dataset inspection. |
| `dataset origin` | Reproducible source pointer for the dataset package. |
| `resolved revision` | Exact revision recorded when acquisition can resolve one. |
| `content hash` | Content fingerprint recorded for reproducibility and conflict detection. |
| `single-dataset experiment` | Experiment model where one experiment references exactly one dataset package. |
| `instance` | One concrete dataset unit over which tasks are executed. |
| `context artifact` | A representation of an instance used by a strategy. |
| `configuration` | Named experimental treatment with required strategy, representation, and surface reference; persisted as `configurationId` and its declared definition. |
| `surface` | Typed context selection declaration. `full_context` selects the complete instance context; `operations` selects an explicit adapter-owned operation list. |
| `representation` | Context representation request passed unmodified to the adapter as the `representation` parameter of `get_context`. It is not a physical filename or file format. |
| `task` | Unit of work to be performed over an instance. |
| `trial` | One planned experimental execution. |
| `response` | Model output produced by executing a trial. |
| `evaluation` | Assessment of a response. |
| `judge vote` | One individual judge assessment. |
| `trace` | Detailed event record of execution or evaluation. |
| `result` | Derived analysis-ready artifact, usually exported as CSV. |
| `metric dimension` | One of five canonical metric groupings computed by `llmctxbench metrics`: effectiveness, efficiency, robustness, evaluation reliability, observability. |
| `run` | One planned experiment in one output directory. In the API, the handle returned by `plan` or `open_run`. Not used for a trial, attempt or request. |
| `execution` / `attempt` | One durable invocation, identified by `executionId` and `attemptId`. |

## Adaptive terms

| Term | Meaning |
|---|---|
| `request` | One workload item before a candidate is chosen: `requestId`, sequence index, task, instance, opaque labels. Repeated task/instance pairs are distinct requests. |
| `candidate` | A model plus a provisioning configuration, with a stable `candidateId`. One catalogue per experiment, identical for every request. |
| `attempt` | The one durable execution of one candidate for one request. A request has at most one attempt. |
| `signal` | A named quantity observed per attempt, with unit and provenance. Built-in signals come from every execution; quality signals (`quality.<metric>`) come from online assessors. |
| `observation` | The signal values, status and failure category of one attempt. |
| `window` | A selection of observations counted in requests: the last `N` (sliding), the current block of `N` (fixed), or the whole run. |
| `reading` | One signal aggregated over one window and scope with one statistic; carries value, provenance and sample counts. |
| `system state` | The read-only view over the causal prefix of observations given to a policy. It contains nothing about the current request. |
| `policy` | A named, versioned decision rule `(candidates, state) → decision`. |
| `decision` | The selection of one candidate for one request, with a reason. |
| `goal` | A bound on a reading. Reported by `metrics`, never enforced. |
| `disturbance` | A seeded delay or failure injected into a runtime component for a range of the sequence. |
| `scenario` | A workload plus disturbances; a helper for building both sections, not a stored type. |
| `definition builder` | A typed fragment of the adaptive definition for experiments written in Python (`Model`, `Configuration`, `Candidate`, `PolicyRef`, `Window`, `Goal`, ...). Stored as the mapping it produces; not a domain entity. |
| `online assessor` | A dataset-provided or external component that turns a response into a quality signal during execution. Distinct from offline evaluation (`eval`). |

The tool does not use the words study, episode, probe, cascade, size bin or burst. An "arm" (one
experimental condition) is study vocabulary; the tool stores only `labels`.

## Instance

An instance is one dataset unit.

Examples:

| Domain | Instance |
|---|---|
| Lattes | one curriculum |
| PDFs | one document |
| source code | one repository or project |
| traces | one execution trace |
| tickets | one ticket or conversation |
| images | one image or image set |

Recommended field:

```text
instanceId
```

## Task

A task is what the model must do. In Q/A, a task may be a question. In a broader benchmark, a
task may be classification, extraction, summarization, ranking, comparison, or tool-mediated
analysis.

Recommended field:

```text
taskId
```

## Trial

A trial is one planned experimental execution:

```text
instance × task × model × configuration × repetition
```

Recommended field:

```text
trialId
```

## Response

A response is the model output for one executed trial.

Recommended file:

```text
responses.jsonl
```

## Evaluation and judge vote

An evaluation is the aggregate assessment of a response.

A judge vote is one individual assessment from one judge.

Recommended files:

```text
evals.jsonl
judge_votes.jsonl
```

## Metrics

`llmctxbench metrics` computes derived, artifact-only metrics from one or more existing run
directories' canonical execution/evaluation artifacts, grouped into five metric dimensions.

Recommended files:

```text
metrics/trial_metrics.csv
metrics/aggregate_metrics.csv
metrics/dimension_summary.csv
metrics/summary.json
metrics/dimensions/{effectiveness,efficiency,robustness,evaluation_reliability,observability}.csv
```

## Naming rules

Use JSON fields with `Id` suffix:

```text
datasetId
experimentId
instanceId
taskId
trialId
modelId
judgeId
```

Use plural file names for JSONL collections:

```text
trials.jsonl
responses.jsonl
evals.jsonl
judge_votes.jsonl
```

## Dataset distribution notes

- `llmctxbench dataset fetch` materializes a dataset into the local dataset cache.
- `llmctxbench dataset inspect` reports a dataset capability report without provider calls.
- lifecycle artifacts preserve dataset provenance as a nested `dataset` object.

## Historical migration reference

This mapping is provided for migration planning only. Public CLI and artifact contracts use the
target terms only and do not expose legacy aliases. For the authoritative artifact reference, see
`docs/architecture/contracts/artifacts.md`.

| Current | Target |
|---|---|
| `copa` | `ctxbench` |
| `query` | `execute` |
| `exec` | prohibited abbreviation; use `execute` |
| `queries.jsonl` | `trials.jsonl` |
| `answers.jsonl` | `responses.jsonl` |
| `runId` | `trialId` |
| `questionId` | `taskId` |
| `answer` | `response` |
| `mcp` | `remote_mcp` |
