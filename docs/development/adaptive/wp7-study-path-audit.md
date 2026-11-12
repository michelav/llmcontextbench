# WP7: RepoQA and study-path audit

## Scope and decision

This audit covers two related but scientifically distinct paths:

1. The RepoQA adaptation protocol in `ctxbench.adapters.repoqa.workflow` and
   `ctxbench.adaptive.runner`.
2. The reusable RepoQA baseline and study protocols in `ctxbench.studies` and
   `ctxbench.adaptive.study_runner`.

Keep both paths operational and preserve their artifact formats during this WP. Do not route
them through the new benchmark or adaptive workflows yet. The shared `TrialExecutionService`
currently owns one invocation and retry record, while these protocols own ordered episode
replay, controller state, treatment instrumentation, and (for cascades) multiple executions
within one request. A migration that changes only the invocation call would leave two competing
recovery authorities or lose protocol-specific measurements. First define and test an adapter
that preserves the sealed protocol packet as the authority and gives each underlying invocation
its own durable execution identity. No legacy path is deprecated by this audit.

## Protocol inventory

| Path | Scientific unit and ordering | Recovery authority | Canonical and derived artifacts | Outcome used |
| --- | --- | --- | --- | --- |
| RepoQA adaptation | A request occurrence is an `EpisodeRequest`; preparation pairs two configurations per instance/repeat. Four targets (16 variants) are calibration-only, and sixteen targets (64 variants) are held out. Held-out order is seeded and balanced by variant across phases. Policies are counterbalanced across seeds. | `adaptive/runner.py` seals `recovery/identity.json` and one `recovery/request-NNNN.json` per occurrence. Resume replays prior decisions/observations and refuses ambiguous started executions unless uncertain retry is explicitly requested. | `prepared.json` freezes dataset, experiment, source fingerprints, split, request candidates and order. `frozen.json` freezes calibration. Episode packets are authority; `trials.jsonl`, `responses.jsonl`, `decisions.jsonl`, `controller-timings.jsonl`, manifests and traces are projections. Analysis consumes those artifacts and optional evaluation rows. | RepoQA’s deterministic scorer provides a `passed` quality outcome when present. Missing evaluation stays unavailable. The paired analysis compares held-out request outcomes, grouped by target/language; it does not use held-out evaluations to update the controller. |
| Frozen baseline | Calibration targets and repetitions are frozen separately from held-out targets. The baseline matrix uses common workload order across configurations, seeds and repeats. | `adaptive/study_runner.py` stores ordered request packets. `baseline.execute` resumes only from packet history; uncertain started attempts require explicit retry and are marked as unknown consumption. `frozen.json` is immutable and requires all planned packets and evaluations. | `prepared.json` freezes the matrix and provenance. Each episode has packet recovery records plus standard benchmark projections, including trials, responses, decisions, traces and evaluations. `frozen.json` records measured observations and hashes of its source artifacts. | Frozen response/evaluation rows establish the calibration estimates and quality summaries used by later studies. Calibration and evaluation target sets are disjoint. |
| Reusable study matrix | Each episode is identified by policy, scenario, seed and repeat. Workloads can be target ordered, deterministically reshaped, or explicitly declared; scenario phases and disturbances are compiled into request ranges. Every policy in a comparison shares its declared request ordering. | The same study runner replays each episode’s sealed packets and controller ledger. A saved selection must match deterministic controller replay. Request/tool delays, fault injection and quota waiting are applied inside measured execution; cascade attempts are recorded under one request and replayed in order. | Study `prepared.json` is bound to one immutable frozen baseline and measurement-source fingerprints. Episode packets are authoritative; benchmark artifacts are projections. `status` is a read-only projection. `analyze` reads saved evaluations and packets and writes analysis output without provider calls. | Request outcomes combine execution status and available evaluation results. Analysis reports paired request and target-level quality/cost/latency metrics, disturbance excess and recovery lags. Evaluation is external to the online controller; post-episode evaluation does not feed policy decisions. |

## Contracts that must survive a migration

- **Identity:** preserve occurrence identity even when task and instance repeat. Keep the episode/request identity separate from the durable execution identity. A cascade request may own multiple attempt execution IDs.
- **Causality:** decisions replay from the sealed ordered prefix. Calibration may inform the controller only through the frozen calibration artifact. Offline evaluation cannot influence an active episode.
- **Order:** keep seeded balancing, counterbalancing, explicit workload validation, scenario phase boundaries, and within-request fallback ordering protocol-specific. Do not replace these with benchmark trial ordering or adaptive candidate ordering implicitly.
- **Recovery:** persist the decision before invocation. Reconstruct completed projections without invoking providers. Preserve the explicit uncertain-retry path and its unknown-consumption accounting. Do not let an execution service independently retry a call behind the protocol ledger.
- **Treatments and measurements:** keep request delay, tool-call delay, server delay, injected faults, and token-quota wait scoped to the declared configuration and request range. Preserve the rule that server delay is invisible to the controller and that measured treatment time is included in the protocol’s latency outcome.
- **Artifacts:** packets remain recovery authority. Standard benchmark artifacts are rebuildable projections and must validate with the existing provisioning/evaluation/export/metrics commands. Frozen plans and baselines stay fingerprinted and immutable.
- **Scientific outcomes:** preserve disjoint calibration/held-out populations, paired comparisons, scorer provenance, missing-quality semantics, and target/language bootstrap units. Minimum response length is not RepoQA accuracy.
- **Cost:** distinguish request-level totals, per-attempt usage, unknown/retried consumption, and evaluation cost. A cascade’s delivered response does not erase the cost or failure of earlier attempts.

## Migration sequence

1. Add an invocation adapter from a protocol attempt to `ExecutionRequest` and `TrialExecutionService`, using deterministic execution IDs derived from the frozen episode and request occurrence plus attempt position. The protocol packet remains authoritative for decision/recovery state; execution records are authoritative only for the underlying invocation result.
2. Specify idempotent reconciliation for the crash window between an execution record completing and its result being copied into the protocol packet. Cover normal attempts and every cascade fallback before enabling the adapter.
3. Run fixture-only equivalence tests: same order, decisions, outcomes, timing/treatment fields, costs, packet replay, and benchmark projections before and after the adapter. Keep provider calls mocked.
4. Migrate the two protocol families independently. Do not merge their policy/state models or make RepoQA assumptions part of the workflow-neutral service.
5. Consider deprecating the old runner only after existing artifacts remain readable, status and analysis are artifact-only, and the equivalence suite passes on both protocol families.

## Existing validation evidence

The current provider-free suite already exercises these contracts in focused tests:

- RepoQA population, calibration/held-out split, balanced seeded ordering, candidate pairing and prompt-budget provenance: `tests/test_repoqa_workflow.py`, `tests/test_repoqa_study.py`.
- Baseline matrix ordering, disjoint target split, immutable freeze, resume, uncertain retry accounting, standard evaluation, export and metrics: `tests/test_study_baseline.py`.
- Study matrix reuse, status, source-drift restrictions, resume, ordering, policy transitions, quotas, delays, faults, cascades, replay and paired analysis: `tests/test_study_protocol.py`, `tests/test_study_replay.py`, `tests/test_study_effects.py`, `tests/test_study_cascade.py`.
- RepoQA adaptation packet replay, projection repair and interrupted-run recovery: `tests/test_adaptive_runner.py`.

These tests are protocol regression gates for any future adapter. They do not yet establish
equivalence with `TrialExecutionService`, so this WP makes no migration or deprecation claim.

## Audit finding repaired in WP7

`MeasuredToolDelay` inherited a delegating runtime but read `runtime`, `delay_ms`, and `sleeper`
from its own instance. Those fields were not retained, so the existing tool-call disturbance
test failed and the episode recorded an error instead of the two delayed calls. The wrapper now
retains those inputs explicitly. `pytest -q tests/test_study_protocol.py::test_tool_delay_records_each_call`
passes, including requested delay, measured delay, call count, and total response duration.
