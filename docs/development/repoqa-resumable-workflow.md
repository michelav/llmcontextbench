# Resumable RepoQA research workflow

The research runner implements the accepted A–E plan. It leaves policy version 2,
decision/run schema 1, provisioning artifact version 2 and the deterministic scorer
unchanged. No paid calibration or held-out study has been run by implementation.

Run commands from the repository root using the existing benchmark environment.
Preparation does not call models. Choose the actual model context limit and output
reservation explicitly; the numbers below are examples, not verified model limits:

```bash
python tools/repoqa/run_adaptation.py prepare \
  --experiment experiment.repoqa-adaptive.json --output runs/repoqa-adaptive \
  --context-limit 200000 --output-reservation 2048
```

Preparation locks all 80 variants, 320 candidate trials, the language-stratified
split and the three shared 64-request schedules. Measured context bytes and explicit
size bins enter the policy; identities and target/language metadata do not. Initial
budgets include the strategy prompt, default system instruction and operation schemas.
An installed local tokenizer is used when supported. Otherwise UTF-8 byte count plus
256 tokens of serialization allowance is a conservative estimate. The overall
budget remains estimated whenever that estimated allowance is included, even with
a tokenizer-derived text count; both components retain their provenance. Tool-loop growth
can still exceed the context window. The reservation also sets the model output cap.

Keep the code revision and source/configuration/dataset files unchanged after
preparation, calibration and freezing. Re-prepare if those inputs change; do not
reuse a frozen calibration across changed settings. `prepared.json`, `frozen.json`
and recovery packets have schema-1 envelopes and content hashes.

The following provider-backed commands require separate cost authorization.
The explicit option is mandatory for real providers; the runner never installs
scorer dependencies. Its scorer smoke check must pass before any paid execution.

```bash
python tools/repoqa/run_adaptation.py calibrate \
  --prepared runs/repoqa-adaptive/prepared.json --output runs/repoqa-adaptive \
  --execute-providers
# Repeat calibration with --delay-ms 100, 250, 500 and 1000.
python tools/repoqa/run_adaptation.py freeze \
  --prepared runs/repoqa-adaptive/prepared.json --output runs/repoqa-adaptive
```

Normal calibration executes 64 selected trials (32 per fixed arm). Each delay
executes 32 local-MCP trials on calibration targets only. Freeze uses the pooled
baseline nearest-rank p90 unless `--application-slo-ms` is supplied. It selects the
smallest delay whose local-MCP p95 is at least 25% higher and whose measured
latencies exceed the objective. Missing/failed normal calibration prevents freezing.
Incomplete delay calibration never qualifies. If no delay qualifies, frozen settings
permit stationary episodes only. Cost projections provide request counts and, after
calibration, estimated tokens; currency remains unavailable without price provenance.

After approving the projected held-out cost, run each seed (20261001, 20261002,
20261003) and allowed scenario. `--policy all` runs all four arms in the recorded
seed/scenario-dependent counterbalanced order. OpenAI prompt-cache keys are partitioned by
arm, seed and scenario; other providers retain their defaults and use that order.
Cache keys do not guarantee provider-side cache isolation.

```bash
python tools/repoqa/run_adaptation.py episode \
  --prepared runs/repoqa-adaptive/prepared.json --output runs/repoqa-adaptive \
  --seed 20261001 --scenario degradation-recovery --policy all --execute-providers
```

Stationary requests have no delay. Degradation/recovery delays each local-MCP tool
invocation on requests 21–44; requests 1–20 and 45–64 have normal latency. The wrapper
preserves discovery, tool results, exceptions and cleanup. Delay is measured within
the full execution duration; existing trial timing retains its original meaning.

## Interruption and recovery

Repeat the exact episode/calibration command with `--resume`. Resume obtains an
exclusive directory lock, validates fingerprints and replays decide/observe from
frozen calibration. Completed successes, errors and unserved observations are final.
A completed episode is verified and returned without further model calls. Downtime
does not advance phases, cooldown or probe schedules.

A saved selection with an execution-start marker but no durable outcome is uncertain.
Resume refuses to repeat it unless `--retry-uncertain` is also supplied. That option
permits possible duplicate provider expenditure and keeps the same selection. Prior
usage remains unavailable; exactly-once provider execution is not guaranteed. Recovery
never restores a model conversation, tool session, client or rate-limit state.

`recovery/request-NNNN.json` atomically records selection before execution, then the
complete trial/result/trace, terminal decision, observation and timing. Canonical
`trials.jsonl`, `responses.jsonl`, trace files and sidecars are atomic projections.
Missing projections are repaired from packets; conflicting rows, duplicates, corrupt
packets and noncontiguous histories fail explicitly. `lifecycle.json` records sessions,
recovery/uncertain events and estimated downtime from the last durable activity. Wall
clock changes and recording gaps limit that downtime estimate. Downtime is excluded
from completed request durations. `controller-timings.jsonl` measures selection and
observation separately, with their sum as controller overhead; replay overhead and
persistence are outside that metric.

## Evaluation and analysis

Only evaluate an episode after all scheduled requests are reconciled. The runner
never receives evaluator/oracle inputs. Use the standard deterministic RepoQA pipeline:

```bash
llmctxbench eval runs/repoqa-adaptive/episodes/stationary/20261001/adaptive-router/responses.jsonl
llmctxbench export runs/repoqa-adaptive/episodes/stationary/20261001/adaptive-router/evals.jsonl \
  --output runs/repoqa-adaptive/episodes/stationary/20261001/adaptive-router/results.csv
llmctxbench metrics runs/repoqa-adaptive/episodes/stationary/20261001/adaptive-router
python tools/repoqa/run_adaptation.py analyze --output runs/repoqa-adaptive
```

Analysis validates completed episodes and joins canonical trials/responses/evaluations
and traces with request identity, decisions, recovery and timing. Identical trial IDs
in different episodes remain separate. Errors/unserved requests are quality failures;
missing successful evaluations make the all-request pass rate unavailable, with
coverage reported. Missing timings/tokens remain unavailable. Known token sums and
known extra usage are reported with incomplete-total flags when prior uncertain usage
or missing tokens exist. Evaluation usage is separate from execution resources.

Reaction delay counts requests through the first non-probe routing change relative to
the phase-entry incumbent; absent changes are censored. Adaptive-minus-frozen comparisons
use paired requests. The 95% percentile bootstrap resamples target groups within each
language, retaining variants/seeds for each sampled target (10,000 replicates, seed
20260929). Missing endpoints reduce paired coverage. Resumed completed episodes enter
primary results; sensitivity retains only complete four-arm scenario/seed blocks with
no resumed episodes. State replay cannot reproduce external provider/cache conditions.

Outputs are `analysis/summary.json`, `timeline.jsonl`, `timeline.csv`, and standalone
SVG timelines when the already-installed matplotlib package is available. Analysis
works without plotting dependencies and never invokes providers or the scorer.

Multi-call token totals are derived from individually saved provider responses.
Missing per-call coverage leaves the complete request total unavailable; known partial
usage still enters resource accounting. Single-call totals reconstructed from reported
input/output counts are derived, and mock lexical counts are estimated. Canonical
usage and trace formats are preserved. Freezing also verifies each calibration
catalog, workload, dataset, budget, source fingerprint and actual delay schedule against
the prepared study.
