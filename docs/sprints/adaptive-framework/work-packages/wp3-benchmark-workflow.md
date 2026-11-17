# WP3 implementation record: benchmark workflow

## Execution boundary

Benchmark planning remains the authority for static assignment. It writes the fixed
configuration for each trial to `trials.jsonl`; execution does not choose or alter a
configuration. Durable benchmark execution now lives in `ctxbench.benchmark.workflow` and
invokes each planned trial through `TrialExecutionService`. The command module validates
artifacts, applies CLI selectors, and delegates the selected trials.

Response rebuilding remains derived from canonical execution records. Evaluation, export,
metrics, and status continue to consume the persisted benchmark artifacts, including when
provider execution is unavailable during analysis.

## Supported execution versions

| Provisioning artifact version | Policy |
| --- | --- |
| 4 | Supported durable execution through the shared execution service. New definition version 3 plans produce this format. |
| 2 and 3 | Existing transitional non-durable execution remains supported for compatibility. The path is unchanged and is not used for new definition version 3 plans. |
| Other versions | Rejected by artifact validation with replan guidance. |

The version split is explicit; no new legacy execution behavior was added. Removing the
transitional branch requires a separate compatibility decision after supported benchmark
behavior has been migrated.
