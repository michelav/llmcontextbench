# Artifact Contracts

This document is the authoritative reference for the CTXBench artifact set, artifact classification, legacy no-alias policy, and metric provenance taxonomy.

## Artifact lifecycle

| Artifact | Producing phase | Class | Role |
|---|---|---|---|
| `manifest.json` | `plan` | `canonical` | Execution artifacts |
| `trials.jsonl` | `plan` | `canonical` | Execution artifacts |
| `responses.jsonl` | `execute` | `canonical` | Execution artifacts |
| `evals.jsonl` | `eval` | `canonical` | Evaluation artifacts |
| `judge_votes.jsonl` | `eval` | `canonical` | Evaluation artifacts |
| `evals-summary.json` | `eval` | `derived` | Analysis-ready exports |
| `results.csv` | `export` | `derived` | Analysis-ready exports |
| `traces/executions/<trialId>.json` | `execute` | `canonical` | Traces |
| `traces/evals/<trialId>.json` | `eval` | `canonical` | Traces |

## Classification rules

Canonical artifacts are the authoritative record of a benchmark phase.

Derived artifacts are reproducible from canonical artifacts without re-invoking providers. Regenerating `evals-summary.json` or `results.csv` must not require re-running `ctxbench execute` or `ctxbench eval`.

## Execution Artifacts

Execution artifacts are the records needed to define and carry out planned benchmark trials.

- `manifest.json` is the plan-phase canonical artifact that records the inputs needed to reproduce subsequent phases.
- `trials.jsonl` is the plan-phase canonical artifact that enumerates the benchmark trials scheduled for execution.
- `responses.jsonl` is the execute-phase canonical artifact that records benchmark responses for completed trials.

### Dataset provenance

Dataset provenance is a nested `dataset` object carried by canonical planning, execution, and evaluation artifacts.

Carrier artifacts:

- `manifest.json`
- `trials.jsonl`
- `responses.jsonl`
- `evals.jsonl`
- `judge_votes.jsonl`

The canonical dataset provenance fields are:

- `dataset.id` required
- `dataset.version` required
- `dataset.origin` optional
- `dataset.resolvedRevision` optional
- `dataset.contentHash` optional
- `dataset.materializedPath` optional operational metadata

Rules:

- `dataset.id` and `dataset.version` identify the dataset package selected during planning.
- `dataset.materializedPath` is additive operational metadata and must not be treated as authoritative identity.
- `plan` is the schema owner for the nested `dataset` object. Later lifecycle phases preserve it; they do not recompute or replace it from another source.
- `results.csv` is the flat export owner for `dataset_id` and `dataset_version`, derived from the canonical nested `dataset` object.

## Evaluation Artifacts

Evaluation artifacts are the canonical records produced by the evaluation phase.

- `evals.jsonl` is the eval-phase canonical artifact containing trial-level evaluation records.
- `judge_votes.jsonl` is the eval-phase canonical artifact containing judge-level voting records used to support evaluation outcomes and agreement analysis.

## Analysis-Ready Exports

Analysis-ready exports are reproducible summaries or tabular outputs intended for downstream analysis.

- `evals-summary.json` is an eval-phase derived artifact reproducible from evaluation-phase canonical artifacts without provider re-runs.
- `results.csv` is an export-phase derived artifact reproducible from canonical artifacts without provider re-runs.

## Traces

Trace artifacts preserve per-trial execution and evaluation observability.

- `traces/executions/<trialId>.json` is the execute-phase canonical trace for one `trialId`.
- `traces/evals/<trialId>.json` is the eval-phase canonical trace for one `trialId`.

### Execution trace metadata

Execution traces record dataset-context metadata using the adapter-boundary vocabulary:

- `instance_id`: canonical instance identifier.
- `context_representation`: the requested logical context representation, derived from the
  trial `format` value and passed to `DatasetPackage.get_context(..., representation)`.
- `context_obtained`: `true` when the execute phase obtained model-facing context through
  `get_context`; `false` for tool-mediated strategies.

Removed execution metadata:

- `context_path`
- `instance_dir`

The legacy `lattes_id` metadata name was renamed to `instance_id`. Strategy internals may retain a
temporary fallback while migration completes, but the artifact contract is `instance_id`.

### Evaluation trace metadata

Evaluation traces record evidence and oracle metadata without exposing oracle values to LLM judge
prompts:

- `evidence_obtained`: `true` when evaluator-facing evidence was obtained from
  `DatasetPackage.get_evidence`.
- `oracle_available`: `true` when `DatasetPackage.get_oracle` returned a value other than the
  `ORACLE_UNAVAILABLE` sentinel.
- `oracle_used`: `false` for judge-based evaluation; oracle values are not included in judge prompt
  construction.

## Metric provenance taxonomy

Every metric in a canonical or derived artifact must be representable under exactly one provenance class per record.

| Class | Definition |
|---|---|
| `reported` | Returned by a provider API, SDK, or another authoritative runtime. |
| `measured` | Measured directly by benchmark-controlled instrumentation. |
| `derived` | Computed deterministically from reported or measured values. |
| `estimated` | Approximated from heuristics, tokenizers, assumptions, or incomplete information. |
| `unavailable` | Not available and not responsibly estimated for that record. |

Rules:

- `estimated` must not be presented as `reported` or `measured`.
- `unavailable` must not be recorded as zero unless zero is the observed value.
- This taxonomy is closed in this specification. It defines exactly five classes and does not permit sub-classes, confidence scores, or other extensions.

## Legacy migration

The following mappings are migration guidance only. Each legacy name has no alias, and migration is the researcher's responsibility.

| Legacy name | Target name | Policy |
|---|---|---|
| `queries.jsonl` | `trials.jsonl` | No alias. Writers and readers use the target name only. |
| `answers.jsonl` | `responses.jsonl` | No alias. Writers and readers use the target name only. |
| `traces/queries/<runId>.json` | `traces/executions/<trialId>.json` | No alias. Writers and readers use the target name only. |
| `trials.jsonl.contextBlock` | `trials.jsonl.contextBlocks` | Breaking key rename. Writers use the target plural key; readers may keep documented migration fallbacks only where needed for old artifacts. |
| `responses.jsonl.contextBlock` | `responses.jsonl.contextBlocks` | Breaking key rename. Writers use the target plural key; readers may keep documented migration fallbacks only where needed for old artifacts. |

No automated migration tooling is committed to by this specification.

## Reader and writer policy

- Writers must produce only target artifact names. No phase writes legacy names.
- Readers do not consume legacy artifact names. If legacy files are present in an input directory, they are silently ignored rather than treated as an error.
- `export` and `status` are artifact-only readers. They must not resolve, inspect, fetch, or
  materialize datasets.
