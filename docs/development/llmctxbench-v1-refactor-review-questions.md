# LLMCtxBench v1 refactor: questions and decisions for the technical lead

Date: 2026-10-23

Status: historical review, addressed by the [accepted simplified design](llmctxbench-v1-refactor-plan.md).
Recommendations below are review history; the accepted plan takes precedence.

Plan reviewed: [LLMCtxBench v1 refactor plan](llmctxbench-v1-refactor-plan.md).

The proposed architecture is sound, but the following decisions should be resolved before implementation. These questions focus on choices that could otherwise produce incompatible implementations or compromise experimental validity. Recommended defaults below are proposals, not accepted decisions.

## 1. Historical preservation and unfinished experiments

Which existing experiments must remain reproducible, which need continued development, and which can be archived as incomplete? For each retained experiment, identify the required definitions, datasets, results, external builders, and dependency versions.

**Required outcome:** a preservation inventory with durable artifact locations and checksums. A Git tag alone does not preserve untracked datasets, outputs, or external sources.

## 2. Safe removal of the legacy stack

S0.2 currently removes modules still imported by the V3 runner: `adaptive/calibration.py` and `adaptive/runner.py`.

**Required change:** extract shared functionality and migrate callers before deleting these modules. Identify which legacy tests protect behavior that the replacement must preserve.

## 3. Request outcomes and fallback semantics

What constitutes the final outcome when a request produces multiple trials? Which attempt supplies the delivered response? Can a controller reject or skip a request without executing a trial?

Define fallback triggers, maximum attempts, configuration reuse, and whether fallback starts fresh or receives previous attempt context.

**Recommended default:** retain every attempt and an explicit request outcome linking the delivered response, final status, cumulative usage, and end-to-end latency. Permit zero attempts for deliberate rejection.

## 4. Crash recovery and authoritative records

Which persisted record is authoritative if a crash leaves trials, responses, decisions, and observations inconsistent? Which files can be reconstructed?

What happens when a provider call may have completed, but its result was not saved? How are controller state, random generators, budgets, cooldowns, and quota windows restored?

**Recommended default:** a durable recovery record governs reconstruction; uncertain external calls require explicit retry authorization and retain uncertainty in cost accounting. Address the current quota-history reset on resume explicitly.

## 5. Controller-visible information

What information may controllers access before a request, after an attempt, and after request completion? Which information is reserved for offline evaluation or oracle reference controllers?

**Required distinction:** a cheap scorer is not necessarily a deployable online sensor. If scoring requires ground truth, declare that access as an experimental condition. Define feature availability and account for feature-extraction or online-validation overhead.

## 6. Calibration, tuning, and held-out evaluation

How are calibration data, parameter-selection data, and held-out evaluation data identified? Is overlap prohibited, permitted with disclosure, or configurable?

**Required outcome:** recorded dataset roles and overlap checks. Simulation-based parameter selection must not silently use held-out outcomes. Debug runs with privileged data must be distinguishable from valid evaluation runs.

## 7. Goals, budgets, and infeasible decisions

For each goal, specify its unit, aggregation window, enforcement mechanism, and missing-data behavior:

- Does latency cover an attempt or the complete request?
- Is a token budget cumulative, per request, or time-window based?
- Do retries, exploration, fallback, and online validation consume it?
- What happens when usage is unknown or every candidate violates a constraint?
- How are utility terms normalized and ties resolved?

**Required distinction:** separate measured service targets from enforceable admission limits. Unknown usage must not count as zero.

## 8. Artifact versions and execution identity

Which schemas change, how are their versions related, and what happens when a command encounters historical artifacts?

Define identities for requests, request occurrences, candidates, trials, runs, and decisions. Specify which resolved inputs affect identity versus a separate execution fingerprint: model parameters, dataset content, surface definitions, MCP mode, workload order, and additional factors.

**Recommended default:** keep provisioning configurations separate from models; represent an adaptation candidate as a model/configuration pair. Classify every new artifact as canonical or derived and specify its authoritative producer.

## 9. Definition composition and frozen plans

What are the exact semantics of `extends`, overrides, and sweeps? Decide relative-path resolution, merge precedence, array replacement, deletion, cycle rejection, expansion order, and generated identifiers.

Are additional `factors` executable treatment axes or descriptive metadata?

**Recommended default:** initially support composition only where needed. Persist the fully resolved definition, frozen workload, and knowledge references at planning time; later source edits must not change a planned execution.

## 10. Provider support and MCP comparability

What provider/model/API/strategy combinations constitute the minimum supported matrix? Which capabilities are validated before execution?

Define tool-loop limits, timeout and retry ownership, authentication references, connection lifetime, and operation restrictions for both MCP execution modes.

**Required correction:** client-hosted MCP provides controlled client-side execution and measurement, not complete visibility into remote internals. Client-hosted and provider-hosted MCP must remain distinguishable in identity, exports, and comparisons. Unsupported restrictions must fail explicitly.

## 11. Metric accounting and aggregation

How are cached tokens, reasoning tokens, partial usage, failed calls, and provider retries normalized without double counting? How does provenance propagate into aggregates?

Which metrics are computed per attempt, request, run, and campaign? Define denominators for skipped requests, failures, missing evaluations, and interrupted runs. Specify formulas for reaction lag, settling time, goal violations, and exploration overhead.

**Recommended default:** keep execution and evaluation costs separate, and use request-level outcomes for delivered quality and service-goal reporting.

## 12. Campaign scheduling and disturbances

Does seeded interleaving operate on complete runs or individual requests? Are requests sequential within a run? Are rate limits, quotas, caches, and connections shared across controllers?

Are disturbances indexed by request occurrence, attempt, tool operation, or elapsed time? How do overlapping disturbances combine? What does “paired under the same disturbances” mean when controllers perform different operations?

**Required outcome:** an explicit scheduling and random-stream contract. A shared seed alone does not guarantee comparable exposure.

## 13. Simulation scope and claims

Does `simulate` mean exact replay, resampling calibration observations, analytical disturbance modelling, or several explicitly separated modes?

What happens when calibration lacks observations for a candidate or feature group? How are unsupported disturbances handled?

**Recommended default:** record simulation assumptions, source data, random seeds, coverage gaps, and estimated provenance. A `simulatable` boolean alone is insufficient.

## 14. Dataset derivation and plugin boundaries

Which transformations must v1 support, and where are their authoritative implementations? Choose between copied content, immutable hard links, and content-addressed storage rather than leaving this to implementation.

Also define the minimum contracts and failure behavior for strategy, validator, feature-extractor, policy, analyzer, and disturbance plugins.

**Required safeguards:** derived datasets must retain source and transformation provenance; modifying a derived dataset must not mutate its base. Generic execution must work with a non-RepoQA adapter.

## 15. Delivery order and acceptance criteria

Which behavior must remain identical, and which existing behavior is intentionally corrected? Historical decision parity should not preserve known defects automatically.

**Recommended sequence:** preserve assets and fixtures → resolve contracts → unify execution → deliver one complete adaptive workflow → expand features → delete superseded code.

Each slice should name dependencies, affected areas, risks, and acceptance checks. Include crash-boundary tests, fallback accounting, unknown usage, leakage prevention, unsupported capabilities, frozen-plan validation, and deterministic tests with injected clocks.

## Expected deliverable

The technical lead’s deliverable should be a revised plan containing these decisions, a small set of representative definition/artifact examples, and acceptance criteria for the first complete adaptive workflow. This should precede the broad rewrite.
