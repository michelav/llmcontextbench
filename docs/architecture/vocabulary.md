# Vocabulary

## Core terms

| Term | Meaning |
|---|---|
| `dataset` | Versioned package of benchmark inputs. |
| `dataset repository` | External source that publishes a dataset package or release asset. |
| `dataset package` | The dataset distribution envelope resolved by CTXBench. |
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
| `format` | Context representation request passed unmodified to the adapter as the `representation` parameter of `get_context`. It is not a physical filename or file format. |
| `task` | Unit of work to be performed over an instance. |
| `trial` | One planned experimental execution. |
| `response` | Model output produced by executing a trial. |
| `evaluation` | Assessment of a response. |
| `judge vote` | One individual judge assessment. |
| `trace` | Detailed event record of execution or evaluation. |
| `result` | Derived analysis-ready artifact, usually exported as CSV. |

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
instance × task × model × strategy × format × repetition
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

- `ctxbench dataset fetch` materializes a dataset into the local dataset cache.
- `ctxbench dataset inspect` reports a dataset capability report without provider calls.
- lifecycle artifacts preserve dataset provenance as a nested `dataset` object.

## Historical migration reference

This mapping is provided for migration planning only. Public CLI and artifact contracts use the
target terms only and do not expose legacy aliases. For the authoritative artifact reference, see
`docs/architecture/artifact-contracts.md`.

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
