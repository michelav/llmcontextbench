# SEAMS 2027 artifact

How to inspect, regenerate and re-run the evidence behind the SEAMS 2027 paper on runtime
adaptation of context provisioning. The scenario guide (`docs/seams2027/scenarios.md`)
explains what each scenario tests; the pre-registration
(`docs/development/seams2027-preregistration.md`) is the binding record of rules,
amendments and outcomes.

## What the artifact supports

| Claim | Evidence | Reproduction level |
|---|---|---|
| RQ1: when adaptation pays off (opportunity map, limit sweep, S-B′, S-F, round-trip) | replay reports, `estimated` | B (provider-free) |
| RQ1: a feasible fallback is required (P3 against P3′) | live pilots | A, C; D to re-collect |
| RQ2: v2 has fewer delay-phase misses and fewer tokens than frozen (H2c′) | S-E′ live study, 60 episodes | A, C; D to re-collect |
| RQ3: lags, probes, switches, controller overhead | S-E′ decision logs | A, C |
| RQ4: v1 against v2; component ablation | S-E′ live; replay ablation (`estimated`) | A, B, C |
| Replay validity | replay against pilots and S-E′ | A, B |

Levels:
- **A:** regenerate the figures and tables from the data archive, in minutes, with no provider calls;
- **B:** re-run replay and parameter selection, in minutes, with no provider calls;
- **C:** re-analyze the live studies from their raw logs, with no provider calls;
- **D:** re-collect with the provider, which costs tokens and hours.

## Contents

| Item | Where | Identity |
|---|---|---|
| Code, definitions, figure and table scripts, generated figures and tables | this repository | paper revision `ea298ac` or later; measurement code frozen at tag `seams-v3-freeze` (`5c09994`) |
| Dataset `ctxbench/repoqa` `2026-10-13-long64.1` | `datasets/repoqa-2026-10-13-long64/` (in git) | sha256 `45f742aed904a52f…` |
| Experiment (6 configurations, `gpt-6-luna`) | `experiment.repoqa-long64-v3.json` | sha256 `55162e80bbfcc9da…` |
| Frozen v3 baseline (calibration) | data archive: `baselines/repoqa-long64-v3/frozen.json` | sha256 `6d78a6e142745fa1…` |
| S-E′ live study | data archive: `studies/seams3-inline-degradation/` | `prepared.json` `af80916e12171d5b…`, `analysis.json` `d0ce63ca6f02ac80…` |
| Frozen v2 baseline (calibration of the P1–P3 pilots) | data archive: `baselines/repoqa-long64-v2/frozen.json`; experiment `experiment.repoqa-long64.json` | sha256 `dc9d1cf06d2ea5ad…`; code at tag `seams-v2-freeze` |
| Pilots P1–P3 (v2), P3′ (v3) | data archive: `studies/pilot-*` | seeds 901–904, never pooled |
| Replay reports and selection records | data archive: `studies/replay-v3calib/`, `studies/replay-validation/` | hashes in the pre-registration |
| Direct-surface provider check (pre-registration amendment, 2026-10-15) | experiment `experiment.repoqa-direct-check.json`; data archive: `runs/direct-check/` | sha256 `7964fa3fb1c78b6b…`; 96 requests on the 4 calibration targets |

The data archive is built with `tools/seams/make_archive.sh` (about 97 MB, 17,488 files,
each listed with its sha256 in the accompanying `SHA256SUMS`). It is deterministic: the same
inputs give the same archive.

```bash
tools/seams/make_archive.sh dist               # full archive: seams2027-data.tar.gz
tools/seams/make_archive.sh dist --anonymize   # review copy: seams2027-data-anon.tar.gz
```

**Double-blind review.** The raw logs contain the absolute path of the author's checkout.
`--anonymize` replaces it with `<repo>` and fails if the home directory still appears. The direct check was run from a
second worktree, so its paths become `<repo>-direct`. The
anonymized copy regenerates every figure and table byte-for-byte (level A). The frozen baselines are sealed with a digest of their original content,
so replay and verification refuse the anonymized copy: levels B, C and D need the full archive
(checked on 2026-10-16: `study replay` reports "corrupt recovery packet"). Git history and
repository metadata also identify the authors, so share the code for review through an
anonymized mirror.

## Requirements

- Linux, Python 3.12.13, `uv`; `uv sync --locked --extra dev` at the repository root.
- RepoQA scorer environment (evaluation, levels C and D): `cd tools/repoqa && uv sync --locked`. On Nix, run RepoQA through `tools/repoqa/repoqa_python` (see `docs/repoqa.md`).
- Level D only: `OPENAI_API_KEY` for the answer model `gpt-6-luna`. Evaluation uses the deterministic RepoQA scorer, with no judge model.
- `jq` and GNU coreutils for the shell scripts; `matplotlib` for the figures.

## A. Regenerate figures and tables (provider-free)

From the repository root, after extracting a data archive into it:

```bash
tar -xzf seams2027-data.tar.gz            # or seams2027-data-anon.tar.gz
python tools/seams/make_figures.py        # docs/seams2027/figures/*.pdf
python tools/seams/make_tables.py         # docs/seams2027/tables/*.tex
python tools/seams/se3_summary.py studies/seams3-inline-degradation   # S-E' table and delay-phase intervals
```

Checked on 2026-10-15: both archives reproduce the committed PDFs and `.tex` files byte-for-byte.

## B. Replay and parameter selection (provider-free)

Replay resamples calibration observations from the frozen baseline and drives the real
controller (`src/ctxbench/studies/replay.py`); outputs are `estimated`. Grids are generated by
`tools/seams/make_grids.py` and are committed in `examples/studies/replay/`.

```bash
B=baselines/repoqa-long64-v3/frozen.json
for g in inline-degradation direct-degradation quota round-trip limit-sweep; do
  llmctxbench study replay --baseline $B --grid examples/studies/replay/v3-$g.grid.json \
    --output studies/replay-v3calib/$g.json
done
python tools/seams/select_parameters.py studies/replay-v3calib/inline-degradation.json \
  --limits 6000,7000,8000 --delays 3000,6000,9000 \
  --infeasible-config local-mcp-direct --feasible-config inline-code-full --baseline $B \
  --rule "seams2027-preregistration v3 S-E'" --output studies/replay-v3calib/selection-inline.json
python tools/seams/select_parameters.py studies/replay-v3calib/quota.json \
  --limits 6000,7000,8000 --quotas 40000,60000,100000,150000 \
  --infeasible-config local-mcp-direct --feasible-config inline-code-full --baseline $B \
  --rule "seams2027-preregistration v3 S-B'" --output studies/replay-v3calib/selection-quota.json
python tools/seams/select_parameters.py studies/replay-v3calib/direct-degradation.json \
  --limits 8000,10000,12000 --delays 1000,2000,3000 --feasible-config local-mcp-direct --baseline $B \
  --rule "seams2027-preregistration v3 S-F" --output studies/replay-v3calib/selection-direct.json
# expected: S-E' and S-B' select; S-F exits non-zero ("the rule fails closed")
python tools/seams/quota_attribution.py > /dev/null   # S-B' attribution, writes quota-attribution.json
```

Checked on 2026-10-15: the S-E′ and S-B′ selection records match the archived ones, and S-F
fails closed. Replay is deterministic under its seeds (201–203, 10 replicates). The
replay-validation grids (`studies/replay-validation/*.grid.json`, in the archive) mirror the
pilot definitions and are replayed the same way.

## C. Re-analyze the live studies (provider-free)

```bash
llmctxbench study status studies/seams3-inline-degradation
llmctxbench study analyze studies/seams3-inline-degradation
python tools/seams/pilot_gates.py --v3     # P3' gates
python tools/seams/pilot_gates.py          # P1-P3 gates (v2)
```

The P1–P3 pilots are bound to the v2 baseline, measured at tag `seams-v2-freeze`. The v3
code adds the direct surface to three RepoQA adapter files, so verifying them with the paper
revision needs `--allow-source-drift`. It reports those three files (`mcp_server.py`,
`provider.py`, `tools.py`) and `_virtualenv.py`; every data hash is still checked. For an exact
match, check out the tool at `seams-v2-freeze`.

`status` and `analyze` verify the study against the frozen baseline: the dataset, the
experiment, every pinned raw artifact, and a fingerprint of the measurement code
(`measurement_sources()` in `src/ctxbench/studies/baseline.py`). The fingerprint includes the
Python files of the RepoQA tool environment (`tools/repoqa/.venv`), and `uv` writes one of them
itself (`_virtualenv.py`), so a different `uv` version changes it. The baseline was frozen
with uv 0.11.14. With another version, verification fails with "measurement source
fingerprint mismatch". In that case add `--allow-source-drift`: it skips only the code
fingerprint, still checks every data hash, and records the drifted files under
`sourceDrift` in `analysis.json`.

**Another location.** The prepared study and the frozen baseline record absolute paths from the
original checkout (`/home/<author>/…/llmcontextbench`; `<repo>` in the anonymized copy). Map
them to the extracted data and the checkout with `--path-map OLD=NEW`. It changes only where
files are read; every hash is still checked:

```bash
R=$(jq -r .payload.baselinePath studies/seams3-inline-degradation/prepared.json | sed 's#/baselines/.*##')
llmctxbench study analyze studies/seams3-inline-degradation --allow-source-drift \
  --path-map $R/baselines=$PWD/baselines --path-map $R=$PWD
```

Checked on 2026-10-15 in a fresh checkout with the full archive and uv 0.11.32:
`study analyze --allow-source-drift` reported `sourceDrift: [".../_virtualenv.py"]` and an
`analysis.json` otherwise identical to the original. That check could still reach the original
checkout through the recorded paths. On 2026-10-16 it was repeated with the original checkout
hidden (`bwrap`), the tool cloned at `seams2027-paper` and the data outside it: `status` and
`analyze` passed with `--path-map`; `analysis.json` and the timeline plots were identical except
for `sourceDrift`, and the figures, tables and S-E′ summary were byte-identical.

## D. Re-collect with the provider (costs tokens)

Each step needs explicit approval of its cost. The numbers are from the original runs:

| Step | Requests | Answer tokens | Wall clock |
|---|---|---|---|
| v3 baseline (6 configurations × 144) | 864 | 8.0M | about 1.5 h |
| P3′ re-pilot (4 arms × 48) | 192 | 2.5M | 20 min |
| S-E′ study (6 arms × 2 scenarios × 5 seeds × 96) | 5,760 | 67.3M | 7 h 23 min |

```bash
# v3 baseline: fixed calibration targets (split seed 42), seeds 101-103, 2 repeats.
# Run from the paper revision; its measurement code is identical to tag seams-v3-freeze.
llmctxbench study baseline prepare --definition examples/studies/baseline.repoqa-long64-v3.json \
  --output baselines/repoqa-long64-v3
llmctxbench study baseline execute --prepared baselines/repoqa-long64-v3/prepared.json
for r in baselines/repoqa-long64-v3/episodes/*/responses.jsonl; do llmctxbench eval "$r"; done
llmctxbench study baseline freeze --prepared baselines/repoqa-long64-v3/prepared.json

# S-E' (and the P3' pilot the same way, from examples/studies/pilot.v3-inline-degradation.json)
llmctxbench study prepare --definition examples/studies/study.seams3-inline-degradation.json \
  --output studies/seams3-inline-degradation
nohup systemd-inhibit --what=sleep:idle --why=seams-collection \
  tools/seams/run_study.sh studies/seams3-inline-degradation \
  > studies/seams3-inline-degradation/collect.out 2>&1 &
```

`run_study.sh` runs seed by seed, shuffles the arm order within each seed with a seeded
shuffle, logs wall-clock times per episode to `episodes.tsv` and evaluates each episode in
the background. It is resumable: re-running it skips evaluated episodes, and a partial
episode is resumed from its sealed per-request packets. A request in flight at a crash is
retried only with `--retry-uncertain`. Any failed request that is not a task failure
(provider or network errors) stops the run with exit 3. The pre-registration then requires
that episode to be discarded and re-run. The original collection needed no resumes,
retries or discards.

A new baseline re-measures the provider. Latency drifts over time (the v2 and v3 calibration
runs differ; `baselines/repoqa-long64-v3/drift-v2-v3.json`), so re-collected live numbers are
expected to differ. The claims to check are the contrasts and their intervals, not exact
counts.

## Metric provenance

- **Answer tokens:** `reported` by the provider. Totals are lower bounds when a request has unavailable usage. That never happened in S-E′.
- **Latency:** `measured` by the harness per request, including injected delays (`delayActualMs`, `toolDelayActualMs`, `quotaWaitMs` are recorded separately).
- **Deadline misses, lags, switches, probe cost, bootstrap intervals:** `derived` from the decision logs.
- **Replay outputs:** `estimated` (resampled calibration observations, arithmetic disturbances).
- **Quality:** the deterministic RepoQA scorer (pass or fail); no LLM judge.

## Known limitations

- One task (RepoQA Search Needle Function), one answer model, one provider, 16 held-out targets reused from v1, injected disturbances, and a local MCP server with no network transport.
- Parameters were selected on 4 calibration targets. The direct surface was added after the v2 pilots failed, as the one allowed fix (pre-registration amendment, 2026-10-15).
- Replay predicts fixed arms and the frozen router within about 1–2 misses per episode, and adaptive routers within 2–6. The limit sweep and the ablation are replay-only.
- The target-cluster bootstrap does not model provider slow periods that correlate requests in time. Report per-seed ranges next to the intervals (`figures/se-tradeoff.pdf`).
