# LLMCtxBench v1 implementation checklist

Authority: [accepted design](../../docs/sprints/v1-refactor/llmctxbench-v1-refactor-plan.md).
States: pending → in progress → verified → complete. Completion requires checks, diff review,
documentation updates and a commit. Record command output summaries and commits in worklog.md.

## S01 — Branch and accepted design

- Status: complete
- Purpose: Reconcile the accepted design, tracking, and target architecture.
- Likely files: `docs/development, docs/architecture, specs/009-llmctxbench-v1` (source paths relative to `src/ctxbench` where applicable).
- Dependency: none.
- Risk: Misrepresenting planned behavior as implemented.
- Suggested commit: `docs: establish tracked v1 refactor plan`.

- [x] Implement the slice's behavior and document its public contract.
- [x] Verify: Documentation links, decision consistency, artifact authority.
- [x] Review diff and record changes, impacts, commands, results and limitations.
- [x] Commit only the verified slice files.

## S02 — Definitions and parameter names

- Status: complete
- Purpose: Separate taskParams/modelParams; validate candidates and single-parent extends.
- Likely files: `benchmark/models.py, experiment_loader.py, runspec_generator.py, schemas, tests` (source paths relative to `src/ctxbench` where applicable).
- Dependency: S01.
- Risk: Silent prompt changes or provider settings in the wrong owner.
- Suggested commit: `refactor: clarify experiment configuration contracts`.

- [x] Implement the slice's behavior and document its public contract.
- [x] Verify: Task rendering; candidate expansion; inheritance paths/precedence/cycles; invalid inputs.
- [x] Review diff and record changes, impacts, commands, results and limitations.
- [x] Commit only the verified slice files.

## S03 — Frozen planning and identity

- Status: complete
- Purpose: Freeze inputs and validate execution identity and artifact versions.
- Likely files: `commands/plan.py, benchmark/provisioning.py, util/artifacts.py, tests` (source paths relative to `src/ctxbench` where applicable).
- Dependency: S02.
- Risk: Combining different executions with identical design IDs.
- Suggested commit: `feat: freeze execution inputs and validate identity`.

- [x] Implement the slice's behavior and document its public contract.
- [x] Verify: Source edits cannot alter snapshots; fingerprint conflicts and old versions fail.
- [x] Review diff and record changes, impacts, commands, results and limitations.
- [x] Commit only the verified slice files.

## S04 — One runtime and dataset boundary

- Status: complete
- Purpose: Route strategies through one runtime with domain-neutral capabilities.
- Likely files: `runtime, benchmark/runtime_adapter.py, benchmark/executor.py, dataset, ai/strategies` (source paths relative to `src/ctxbench` where applicable).
- Dependency: S03.
- Risk: Changing transport behavior while consolidating execution.
- Suggested commit: `refactor: unify runtime and dataset boundaries`.

- [x] Implement the slice's behavior and document its public contract.
- [x] Verify: Fake-adapter strategy regressions and import boundaries.
- [x] Review diff and record changes, impacts, commands, results and limitations.
- [x] Commit only the verified slice files.

## S05 — Usage and timing

- Status: complete
- Purpose: Preserve complete/partial expenditure and directly measured latency.
- Likely files: `ai/models, ai/trace.py, runtime, metrics, tests` (source paths relative to `src/ctxbench` where applicable).
- Dependency: S04.
- Risk: Double counting and treating unknown expenditure as zero.
- Suggested commit: `fix: standardize execution accounting`.

- [x] Implement the slice's behavior and document its public contract.
- [x] Verify: Cached/reasoning tokens; retries; failed calls; unknown totals; provenance.
- [x] Review diff and record changes, impacts, commands, results and limitations.
- [x] Commit only the verified slice files.

## S06 — Durable execution and lifecycle readers

- Status: complete
- Purpose: Persist atomic attempts; recover and rebuild collections consistently.
- Likely files: `benchmark/checkpoints.py, commands/{execute,eval,export,status,metrics}.py, tests` (source paths relative to `src/ctxbench` where applicable).
- Dependency: S05.
- Risk: Duplicate external execution or loss of failure expenditure.
- Suggested commit: `feat: persist execution records and support recovery`.

- [x] Implement the slice's behavior and document its public contract.
- [x] Verify: Completed attempts never rerun; uncertain retries distinct; lock/corruption handling; static lifecycle.
- [x] Review diff and record changes, impacts, commands, results and limitations.
- [x] Commit only the verified slice files.

## S07 — Providers and remote MCP

- Status: complete
- Purpose: Explicit providers/capabilities, preserved judge params, client-hosted remote MCP.
- Likely files: `ai/models, ai/engine.py, ai/runtime, ai/rate_control.py, tests` (source paths relative to `src/ctxbench` where applicable).
- Dependency: S06.
- Risk: Assuming identical provider capabilities or token semantics.
- Suggested commit: `feat: standardize providers and remote MCP execution`.

- [x] Implement provider resolution, client-hosted remote MCP and judge parameter preservation; document public contract.
- [x] Verify: Provider fixtures; fake MCP; unsupported mode and operation restrictions.
- [x] Review diff and record changes, impacts, commands, results and limitations.
- [x] Commit only the verified slice files.

## S08 — Minimal adaptive lifecycle

- Status: complete
- Purpose: Static/threshold control, knowledge, explicit/phased workloads, tool delay, all lifecycle commands.
- Likely files: `adaptation, commands, benchmark, tests, examples/adaptive-minimal` (source paths relative to `src/ctxbench` where applicable).
- Dependency: S07.
- Risk: Hidden RepoQA coupling or evaluation evidence in control.
- Suggested commit: `feat: add minimal adaptive experiment lifecycle`.

- [x] Implement static/threshold selection, frozen calibration knowledge, explicit workloads/phases, request records, tool delay, lifecycle readers and example; document the public contract.
- [x] Verify: Fake dataset calibration metrics and overlap rejection; deterministic selection; empty eligibility; injected delay; adaptive plan/execute/status/export/metrics smoke check.
- [x] Review diff and record changes, impacts, commands, results and limitations.
- [x] Commit only the verified slice files.

## S09 — Fallback and request outcomes

- Status: complete
- Purpose: Ordered fresh attempts; accepted delivery; sensors and cumulative request expenditure.
- Likely files: `adaptation, metrics, tests` (source paths relative to `src/ctxbench` where applicable).
- Dependency: S08.
- Risk: Mistaking execution success for accepted delivery.
- Suggested commit: `feat: add fallback and delivered request outcomes`.

- [x] Implement the slice's behavior and document its public contract.
- [x] Verify: Failure then success; sensor rejection; candidate exhaustion; interruption; all-attempt accounting.
- [x] Review diff and record changes, impacts, commands, results and limitations.
- [x] Commit only the verified slice files.

## S10 — Additional controllers and disturbances

- Status: complete
- Purpose: Utility/circuit breaker/budget/exploration and required disturbances using existing interfaces.
- Likely files: `adaptation, tests` (source paths relative to `src/ctxbench` where applicable).
- Dependency: S09.
- Risk: Changing budget or disturbance semantics silently.
- Suggested commit: `feat: extend adaptive policies and disturbances`.

- [x] Implement the slice's behavior and document its public contract.
- [x] Verify: Admission/best effort; unknown estimates; quota restoration; deterministic random streams.
- [x] Review diff and record changes, impacts, commands, results and limitations.
- [x] Commit only the verified slice files.

## S11 — Research preparation and analysis utilities

- Status: complete
- Purpose: Workloads, seeded resampling, knowledge diff, materialized derivation and simple reports.
- Likely files: `adaptation, dataset, adapters, commands, metrics, tests` (source paths relative to `src/ctxbench` where applicable).
- Dependency: S10.
- Risk: Expanding into a simulation or storage framework.
- Suggested commit: `feat: add experiment preparation and analysis utilities`.

- [x] Implement the slice's behavior and document its public contract.
- [x] Verify: Lineage overlap; missing coverage; deterministic sampling; base immutability; paired differences.
- [x] Review diff and record changes, impacts, commands, results and limitations.
- [x] Commit only the verified slice files.

## S12 — Remove superseded code

- Status: complete
- Purpose: Remove replaced stacks and update final architecture and examples.
- Likely files: `adaptive, studies, commands, adapters/repoqa, tests, docs` (source paths relative to `src/ctxbench` where applicable).
- Dependency: S11.
- Risk: Deleting useful behavior before replacement coverage.
- Suggested commit: `refactor: remove superseded adaptive implementations`.

- [x] Implement the slice's behavior and document its public contract.
- [x] Verify: Caller audit retained independently used study protocols; provider-free regression suite; old-version rejection.
- [x] Review diff and record changes, impacts, commands, results and limitations.
- [x] Commit only the verified slice files.
