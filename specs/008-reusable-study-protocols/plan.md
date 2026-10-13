# Implementation plan

Status: implemented with provider-free fixtures on 2026-10-13. Read `spec.md` for contracts.
This replaces the earlier ten-slice plan. Live provider collection remains pending.

## Design decisions

Two authored definitions: baseline and study. Keep existing experiments. A baseline
owns the split and stationary episode matrix; freeze includes derived estimates in
one manifest. Studies inherit population/configuration/settings and specify policies,
integer seeds, repetitions, scenarios and comparisons. Generate hashes/IDs/provenance
internally. No seed aliases, episode groups, snapshot lifecycle, generic feature or
analysis language, or new automatic disturbance calibration.

Use the existing lean operation plan's contracts and benchmark execution machinery.
Add study modules only as their responsibilities become concrete. Keep RepoQA mapping
in the adapter and control/recovery in `adaptive/`. Legacy protocol remains separate.

## Implementation slices

Each slice includes its CLI/documentation changes when needed; do not postpone all
usability until every policy is implemented. One green commit per slice. Generate
focused tasks after design acceptance.

### 0. Preserve operation errors through MCP

- Goal: fix the confirmed loss of `ToolResult.is_error` at RepoQA's registered
  MCP handlers, before collecting new baselines or comparing execution reliability.
- Files: RepoQA `mcp_server.py`; `tests/test_repoqa_tools.py` and surface tests;
  inspect the equivalent Lattes handlers and add a reproducer before applying the
  same correction there if affected.
- Design: preserve the service error flag in the protocol-level MCP response using
  the installed SDK's supported result API, retaining normalized error content and
  successful payloads. Do not infer failure from an `error` dictionary key in the
  generic runtime. Operation failures remain distinct from transport failures and
  need not make the entire request fail if the model subsequently recovers.
- Checks: missing file, unavailable visible content, missing symbol and success
  through the actual MCP runtime; compare content/flags with direct local functions;
  fixture strategy execution records `isError: true` in the trace and forwards the
  error status to the next model step. Existing success/surface tests remain green.
- Dependencies: none; independently shippable bug fix. Risks: changing error payload
  shape or turning recoverable tool results into thrown transport exceptions.
- Compatibility: preserve historical traces; document the old false flags. A corrected
  measurement implementation requires fresh compatible baselines, not re-sealing old
  inputs or relaxing resume fingerprints. No provider calls or SDK upgrades needed.
- Commit: `fix(mcp): preserve operation error flags through server handlers`.

### 1. Lean configurations and failure evidence

- Goal: expose equivalent lean operations through MCP/functions and audit saved
  failures to establish whether reliability adaptation has a defensible target.
- Files: RepoQA provider/tools/package/MCP server; tool/surface tests; new example
  experiment; bounded audit report under this spec. Existing runs unchanged.
- Checks: visibility/filtering, IDs, complete code, deterministic output, default
  compatibility, model-visible transport parity, byte counts; error counts reconcile
  and unknown classifications remain explicit. No provider execution.
- Dependencies: slice 0 and accepted operation contracts. Risks: quality loss, extra tool calls,
  attributing shared errors to transport.
- Commit: `feat(repoqa): add equivalent lean operation surfaces`.

### 2. Baseline preparation, execution and freezing

- Goal: schema, deterministic split/matrix, generalized fixed-candidate execution,
  reusable frozen baseline containing observations and estimates. Deliver baseline CLI.
- Files: new study models/workflow as needed, commands/study.py, cli.py; RepoQA study/
  workload helpers; adaptive runner/calibration/sidecars as needed; schemas/examples.
- Checks: integer seeds; configuration × seed × repeat counts; two/five candidates;
  target isolation; repeated execution not multiplied by experiment repeats; local
  function context-fit budgeting; complete/failed/missing/evaluated records; hashes;
  immutable freeze; all-sample summaries; interrupted execution replay and legacy parity.
- Dependency: slice 1 for real lean examples. Risks: trial identity, dropped failures,
  incompatible measurement reuse. Fixed-arm generalization belongs here, not later.
- Commit: `feat(study): prepare and freeze reusable baselines`.

### 3. Study preparation and generalized latency episodes

- Goal: study schema inheriting baseline inputs; compatible reuse; fixed/frozen/
  adaptive multi-candidate policies; explicit request/tool delays; CLI/status/analysis.
- Files: study models/workflow, commands, adaptive policy/types/runner/recovery/
  sidecars, RepoQA analysis, fixture definitions and tests.
- Checks: same baseline reused across definitions; incompatible changes rejected;
  persisted held-out ordering; N-candidate ties/probes; optional objective validation;
  fake-clock delay placement; phase lengths; same schedules across arms; independent
  state; resume; planned versus completed matrix and paired analysis.
- Dependency: slice 2. Risks: scientific drift, delays outside measured interval,
  confusing per-call and per-request treatments. Explicit delay selection must use
  calibration/pilot evidence; no new sweep engine in this slice.
- Commit: `feat(study): run declarative latency adaptation episodes`.

### 4. Token-budget policy

- Goal: remaining-work forecast, durable budget ledger, baseline comparisons, and
  quality eligibility from calibration only; add policy example/CLI validation.
- Files: adaptive policy/state/accounting helpers and sidecars; study schema and
  analysis; token/budget/recovery tests and docs.
- Checks: count all known steps/failures/probes once; unknown usage stops execution;
  infeasible work recorded unserved; overshoot; cheapest-qualified fixed comparator;
  no scoring leakage; ledger identical after resume.
- Dependency: slices 2–3. Risks: estimates mistaken for hard guarantees or money,
  small calibration samples used as proof of quality equivalence.
- Commit: `feat(adaptive): select configurations within episode token budgets`.

### 5. Across-request reliability adaptation

- Goal: classify observable failures and change future selections; expose only
  evidence-justified parameters. No same-request fallback.
- Files: adaptive observations/policy/sidecars; structured runtime mapping where
  available; study schema, reliability fixtures, analysis and docs.
- Checks: transport/shared/unknown distinctions; threshold/window/minimum samples;
  cooldown/recovery probing; errors distinct from wrong answers; no ground-truth
  feedback; replay; fixed local-function and MCP comparators.
- Dependencies: slice 1 audit and slice 3 engine. Independent of budget research.
- Risks: sparse failures and shared causes do not justify transport superiority.
- Commit: `feat(adaptive): route on classified execution failures`.

### 6. Research and compatibility audit

- Goal: review individual study evidence, contracts and documentation before proposing
  a combined policy. The audit does not require automatic paid execution.
- Files: spec/research notes, maintained guides, old lean-plan scope update after
  acceptance, regression fixtures where gaps are identified.
- Checks: no silent old schema changes; standard eval/export/metrics still work;
  no omitted failures/unserved requests; generation/evaluation accounting separated;
  dependent observations not presented as independent replications; no unintended
  provider calls in help/prepare/freeze/status/analyze.
- Dependencies: relevant completed slices. Risk: claiming adaptive benefit when a
  fixed configuration dominates.
- Commit: `docs(study): document validated protocols and compatibility`.

## Deferred scope

Combined policy and its conflict priorities need evidence from individual studies.
Also defer same-request fallback, repeated split campaigns, custom split imports,
baseline merging/extension, standalone estimator snapshots, stale-baseline treatments,
monetary budgets and generic plugin/feature/analysis frameworks. This does not remove
those research directions; it removes them from the first implementation contract.

## Validation and migration

Use focused fixture tests for each slice, then relevant surface, adaptive, recovery,
accounting, CLI and analysis regressions. Preserve old prepared/frozen records and
strict resume checks. New manifest/sidecar versions are explicit; no silent upgrade
or re-sealing. Provider calls require separate user authorization and cost disclosure.
No dependency or lockfile changes are planned.

This revision changes documentation only: validate JSON examples/process logs, local
references and whitespace. Runtime tests are unnecessary until implementation begins.
