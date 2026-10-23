# LLMCtxBench v1 specification

Status: accepted; Level 3 architectural/schema/provider change.

The normative requirements, exclusions and migration policy are in the
[accepted design](../../docs/development/llmctxbench-v1-refactor-plan.md).
The [architecture contracts](../../docs/architecture/v1-contracts.md) specify ownership and recovery.
The [tasks](tasks.md) define delivery gates; [worklog](worklog.md) records evidence.

Success means a provider-free worked example can plan, execute, evaluate, export, inspect and measure
both static and adaptive experiments, including failed/uncertain attempts, admission rejection and
fallback. It must preserve individual judge votes, separate evaluation expenditure, detect calibration
leakage and never portray unknown usage as zero. Claude and Gemini must pass adapter fixture contracts;
live verification is a separately authorized activity. Superseded code is removed only after migration.

Implementation is authorized slice by slice without repeated permission requests for ordinary edits
and provider-free verification. Paid runs, dependency changes and publication remain separate actions.
