# Run manifest (`manifest.json`)

Every run directory has one `manifest.json`, written by `plan`. It identifies the workflow kind,
the artifact versions and the execution fingerprint. `WorkflowRegistry.for_run` reads it to
select the workflow: a manifest with `workflowKind: "adaptive"` is an adaptive run; any other
manifest is a benchmark run.

## Adaptive manifest

Writer and validator: `ctxbench/adaptive/artifacts.py` (`write_adaptive_artifacts`,
`validate_workflow_manifest`). The key set is exact.

| Key | Value |
|---|---|
| `schemaVersion` | `3` |
| `workflowKind` | `"adaptive"` |
| `adaptiveArtifactVersion` | `3` |
| `adaptivePlanVersion` | `4` |
| `executionRecordVersion` | `1` |
| `experimentId`, `workflowId` | The plan's `workflowId`. |
| `executionFingerprint` | SHA-256 of `adaptive-plan.json` ([plan contract](adaptive-plan.md)). |
| `dataset` | Dataset provenance: `id`, `version`, `origin`, `resolvedRevision`, `contentHash`, `materializedPath` where available. The materialised path is operational metadata, not identity. |
| `evaluation` | Offline evaluation settings (`enabled`, `judges`). |
| `trace` | Trace settings. |
| `labels` | Run labels from the plan. |
| `privileged` | `true` when any declared online assessor uses reference data. A privileged run cannot be presented as deployable behaviour; metrics carry the flag. |
| `seed` | The plan seed. |
| `mixedModels` | The plan's `allowMixedModels`. |

The manifest has no `fingerprintInputs` and no plan digest of its own: the plan is the
fingerprint.

## Benchmark manifest

Writer: `BenchmarkWorkflow.plan` in `ctxbench/benchmark/workflow.py`. Verifier:
`ctxbench/core/fingerprint.py::verify_snapshot`.

| Key | Value |
|---|---|
| `schemaVersion` | `3` |
| `provisioningArtifactVersion` | `4` |
| `executionRecordVersion` | `1` |
| `configurations`, `surfaces` | The resolved provisioning configurations and surfaces in the trial matrix. |
| `experimentId`, `experimentPath` | Definition `id` and the absolute path of the definition file (`null` for a definition passed as a mapping). |
| `dataset` | Dataset provenance, as above. |
| `evaluation`, `trace`, `artifacts` | The definition's evaluation, trace and artifact settings. |
| `fingerprintInputs` | `{"artifacts": {"resolved.json": <sha256>, "trials.jsonl": <sha256>}, "implementation": <sha256>, "dataset": <sha256 or contentHash>}` |
| `executionFingerprint` | Digest of `fingerprintInputs`. |

`execute` on a benchmark run verifies the frozen artifacts, the implementation and the dataset
against `fingerprintInputs`.

## Version policy

Older manifest versions are rejected with a message to create a fresh plan. There is no
migration.
