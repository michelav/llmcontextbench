# LLMCtxBench v1 worklog

## S10 — complete

- Added calibrated utility selection, a rolling failure-window circuit breaker with one fallback,
  token-budget admission with explicit best-effort behavior, and deterministic seeded exploration.
- Added rolling token-quota admission with persisted per-attempt usage timestamps, quota restoration,
  unknown-usage blocking in strict mode, measured quota waits, and best-effort override. Admission
  estimates remain separately recorded from observed expenditure.
- Extended phases with seeded deterministic tool-call failure injection alongside the existing delay.
  Updated the definition schema, public architecture contract, and adaptive example guidance.
- Validation: focused adaptive, accounting, calibration, and definition suites (49 passed); Python
  compilation, JSON schema parsing, and `git diff --check` passed. No provider calls or dependency
  changes. Limitations: token quota admission uses calibrated/runtime mean estimates and can overshoot
  when actual usage differs; best-effort explicitly permits unknown or infeasible estimates.
- `token_provenance: "unavailable"`.
- Commit: `feat: extend adaptive policies and disturbances` (hash recorded in Git history).

## S09 — complete

- Added a bounded cascade policy with one optional fallback. Execution tries eligible candidates in
  configured order, persists each attempt reference, and distinguishes delivered, failed, and
  admission-rejected requests. A deterministic minimum-response-length sensor can reject successful
  attempts and trigger fallback; rejected responses are never marked as delivered.
- Request records aggregate measured attempt duration and complete/known token usage while retaining
  per-attempt accounting. Sensor duration and its zero model-token cost are recorded separately.
- Updated the v1 definition schema and architecture/example documentation.
- Validation: `pytest -q tests/test_adaptive_v1.py tests/test_adaptive_v1_fallback.py
  tests/test_v1_definitions.py` (21 passed); Python compilation, JSON schema syntax parsing, and
  `git diff --check` passed. Coverage includes failure then success, sensor rejection, exhaustion,
  interruption/uncertain recovery, aggregate known and complete usage, and schema constraints.
- Impact: request delivery is now separate from execution success; all automatic fallback expenditure
  remains visible, with unknown totals preserved as unavailable. Evaluation expenditure stays separate.
- No provider calls or dependency changes. `token_provenance: "unavailable"`.
- Commit: `feat: add fallback and delivered request outcomes` (hash recorded in Git history).

## S08 — complete

- Implemented schema and planning support for static and threshold adaptive definitions, explicit
  request order, candidate eligibility, size bins, and phased tool delay.
- Threshold plans freeze derived estimates from a separate static run; overlapping calibration and
  evaluation requests are rejected. The knowledge file and adaptive plan are included in the execution
  fingerprint.
- Execution serially records each adaptive decision and reference to the durable trial attempt.
  `requests.jsonl` is derived from these records; the shared response/eval/export/metrics lifecycle
  remains the source for selected trial results. Status reports request-level progress.
- Added a mock-backed minimal example and regression tests for deterministic selection, missing
  candidates, derived calibration and leakage, and delay injection.
- Validation: focused tests (24 passed), source compilation, and fake example plan/execute/status/
  export/metrics smoke checks passed.
- Limitation: one attempt per request (`repeats=1`); S09 owns fallback and accepted-delivery outcomes.
- Commit: `feat: add minimal adaptive experiment lifecycle` (slice commit; hash is in Git history).

## S01 — complete

- Created `refactor/llmctxbench-v1` from `r3`; existing untracked research data preserved.
- Replaced superseded draft with accepted simple design; added slice checklist and specification.
- Architecture distinguishes implemented baseline from target behavior.
- Historical freeze tags found; Zenodo reference not present locally and requested from owner.
- No provider calls or dependency changes.

- Validation: local links checked in five primary documents; `git diff --check` passed.
- Tests not run: documentation-only slice, no runtime changes.
- Impact: accepted target is explicit, while existing architecture pages remain clearly labelled as the current baseline.
- Commit: `docs: establish tracked v1 refactor plan` (see branch history).

## S02 — complete

- Added version-3 definition validation with taskParams, modelParams, explicit candidate pairs,
  separate execution.options, inheritance and a published JSON Schema.
- Candidate planning preserves the selected pairs rather than creating an unintended cross product.
- Judge references retain generation parameters; dataset task substitutions retain their meaning.
- Transitional implementation: definition input is normalized once into the existing planner models;
  persisted trial field names migrate with readers/writers in S03/S06. Unversioned definitions remain
  for the existing study stack until S12; no new historical artifact reader was added.
- Validation: 45 focused definition/provisioning/schema/fake-dataset tests passed; diff check passed.
- Impact: v1 definitions are usable without replacing the runtime or altering existing study inputs.
- Commit: `refactor: clarify experiment configuration contracts`.

## S03 — complete

- Versioned plans freeze resolved.json and trials.jsonl with content hashes, implementation/dependency
  fingerprint and dataset digest. Full-length trial IDs use design keys. Execution verifies the
  fingerprint; artifact-only readers verify snapshot integrity without accessing the dataset.
- Cross-directory validation rejects conflicting fingerprints for an experiment identity.
- Transitional boundary: version-2 artifacts remain supported only by the existing stack until S12;
  version-3 artifacts require the frozen fingerprint. Public trial field migration remains in S06.
- Validation: 33 focused planning/definition/provisioning tests passed, including source edit,
  implementation edit, dataset edit, tampered snapshot and unknown-version cases. Diff check passed.
- Impact: editing a definition cannot change a saved execution; code/data changes require replanning.
- Commit: `feat: freeze execution inputs and validate identity`.

## S04 — complete

- Consolidated provisioning behind a domain-neutral runtime and shared local function/client-MCP
  tool loop; removed benchmark-specific inline execution and runtime-to-benchmark imports.
- Dataset packages now expose instructions, surfaces, MCP server, request features and validators
  through the package contract. Lattes-specific environment parsing lives in its adapter; evaluation
  dispatches through validator registration.
- Impact: execution and evaluation boundaries are simpler while current strategy behavior and
  first-party dataset support remain intact. Expenditure/timing standardization remains S05.
- Validation: 219 focused runtime, strategy, adapter, CLI and lifecycle tests passed; `git diff --check`
  passed. No provider-backed commands or dependency changes were used.
- Commit: `refactor: unify runtime and dataset boundaries`.

## S05 — complete

- Added measured model-attempt counts, failures and elapsed spans, including failed calls and
  automatic retries. Trial request duration now comes from the runtime's monotonic measurement and
  includes context preparation and waits, independent of trace-file settings.
- Token aggregation now distinguishes complete totals from known subtotals. `totalTokens` stays null
  if any model call or failed attempt has unknown usage; `knownTotalTokens`, `totalTokensProvenance`
  and `usageCompleteness` make partial accounting explicit. Export and metric rows expose these fields.
- Impact: failed requests retain measured time and unknown expenditure is not silently treated as
  zero; cached and reasoning token details remain separately reported. Provider failures that return
  no usage cannot reveal exact expenditure, so only their elapsed time and unknown status are saved.
- Validation: 129 focused AI, runtime, metric, CLI, export and adaptive token accounting tests passed;
  `git diff --check` passed. No provider-backed commands or dependencies were used.
- Commit: `fix: standardize execution accounting`.

## S06 — complete

- New schema-version-3 plans use provisioning artifact version 4 and execution-record contract 1.
  Execution writes an atomic `started` record before dispatch, then replaces it with a terminal
  record containing the self-contained response. A POSIX advisory lock prevents concurrent writers;
  file and directory sync protect the atomic replacements.
- `responses.jsonl` is rebuilt from the latest terminal attempt in plan order. Completed successes
  and failures are skipped on resume; uncertain `started` records block until `--retry-uncertain`
  creates a new attempt ID, retaining the earlier record. `--force` creates another explicit attempt.
  Eval, status, export and metrics rebuild the derived collection without a provider or dataset.
- Impact: interruption leaves an inspectable uncertain attempt rather than an absent/ambiguous response;
  corruption and fingerprint mismatches stop recovery. Version-2/3 artifact flows remain transitional.
- Validation: 143 focused execution-record, frozen-plan, CLI, lifecycle, artifact, metrics, AI and
  runtime tests passed; `git diff --check` passed. Execution tests used local mock providers only.
- Commit: `feat: persist execution records and support recovery`.

## S07 — complete

- Provider resolution now uses explicit provider identifiers and rejects unknown values rather than
  silently selecting the mock adapter. Tool-calling capability is declared by provider adapters;
  mock rejects tool strategies while OpenAI, Anthropic and Google accept client-side function calls.
- `remote_mcp` now uses the shared client tool loop and connects from the benchmark process. Its
  endpoint and credentials stay in the client runtime; model requests carry function declarations.
  Surface operation allow-lists filter advertised tools and guard calls. Judge-specific generation
  parameters remain merged with structured-output defaults.
- Impact: tool calls and their timing/results are visible to ctxbench for remote as well as local
  MCP. Unknown provider typos fail clearly. Remote MCP verification uses fake runtimes and makes no
  network or provider calls. Provider token semantics remain provider-reported.
- Validation: `tests/test_ai.py` (50 passed) and `tests/test_runtime.py`,
  `tests/test_mcp_operation_errors.py`, `tests/test_repoqa_evaluation.py` (21 passed); focused
  provider/MCP/judge selection (13 passed); `git diff --check` passed.
- Commit: `feat: standardize providers and remote MCP execution`.
# S11 — complete

- Added provider-free deterministic workload sampling with declared lineage-group exclusions,
  seeded calibration bootstrap with estimated provenance and explicit missing-coverage failures,
  immutable knowledge diffs, full-tree derived dataset materialization with provenance, and paired
  request difference summaries with incomplete-pair coverage.
- Public contract: `docs/development/adaptive-research-utilities.md`. Dataset-specific filtering and
  lineage discovery remain adapter responsibilities; derivation copies the base tree unchanged.
- Validation: `PYTHONPATH=src pytest -q tests/test_adaptive_research.py tests/test_adaptive_v1.py`
  (10 passed); `git diff --check` passed. No provider calls.
- Limitations: materialization records selected requests but does not rewrite/filter source data;
  bootstrap supports numeric row fields and is explicitly estimated.
