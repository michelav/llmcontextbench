# SEAMS 2027 scenario guide

A readable overview of the scenarios behind the SEAMS 2027 paper: what each one tests, how
it is run, and where its evidence comes from. The binding record of rules, amendments and
outcomes is `docs/development/seams2027-preregistration.md`; this guide summarizes it and
does not change it. Status as of 2026-10-15.

## The research question in one paragraph

An LLM application can provide code context in several ways (configurations). Some are
fast but expensive in tokens; others are cheap but slower. A **router** picks a
configuration for every request under a **latency limit** (a deadline per request). A
router built only from design-time measurements (calibration) works while conditions
stay as measured. The paper asks **when runtime feedback (a MAPE-K loop) pays off** —
detecting that conditions changed and switching configuration — and how much it costs.

## Terms

| Term | Meaning |
|---|---|
| Configuration | strategy × representation × surface, e.g. `inline-code-full` (code pasted in the prompt) or `local-mcp-direct` (local MCP server with the direct surface) |
| Surface | the set of operations a tool configuration exposes: `default` and `lean` (list files → list symbols → get symbol), `direct` (`find_symbol` search returning code) |
| Episode | 96 requests (16 held-out targets × 6 context sizes), one policy, one scenario, one seed |
| Arm | the policy used in an episode (fixed configuration, frozen router, adaptive router, oracle) |
| Deadline miss | a request slower than the latency limit; the main metric |
| Frozen router | chooses by calibration estimates per size bin; never updates them (same catalogue, no feedback) |
| v1 / v2 router | adaptive routers that update estimates from observed requests; v2 adds a pooled estimator, estimate expiry (TTL), quantile routing and targeted probing |
| Oracle | a schedule that knows when the disturbance starts and ends and uses the best configuration per phase; an upper bound, not a deployable policy |
| Opportunity | frozen misses − oracle misses: the room adaptation has to help |
| Capture | the share of the opportunity an adaptive router recovers |
| Replay | provider-free simulation over calibration measurements (see below) |
| Live | real provider calls through the study engine |

## The configuration catalogue (v3 calibration)

`baselines/repoqa-long64-v3`, 144 requests per configuration on the 4 calibration targets;
all passed.

| Configuration | Median latency | p90 | Model calls | Tokens per request |
|---|---|---|---|---|
| inline (full) | 3.4 s | 5.0 s | 1.0 | 16.3k |
| MCP direct | 4.6 s | 7.2 s | 2.2 | 3.2k |
| MCP lean | 6.7 s | 9.5 s | 3.9 | 5.6k |
| function lean | 6.8 s | 10.4 s | 3.9 | 5.6k |
| function default | 7.1 s | 11.3 s | 3.8 | 12.1k |
| MCP default | 7.3 s | 11.7 s | 3.9 | 12.5k |

Tool configurations are slow because of sequential model calls (about 1.4 s each), not
because of the tools or the transport (about 10 ms and 30 ms per request). The direct
surface was designed to remove those calls (worklog, 2026-10-15).

## Scenarios

### S-E′ — inline degrades, the router should move to direct (live)

- **Question:** can feedback detect that the fast, expensive incumbent became slow, move to a cheaper configuration that still meets the deadline, and return afterwards?
- **Setup:** catalogue inline and MCP direct; limit 7 s. Normally only inline meets 7 s reliably (direct's p90 is about 7.2 s), so the frozen router always uses inline. During requests 31–60 inline is delayed by 9 s per request; then it recovers.
- **Arms:** fixed inline, fixed direct, frozen, v1, v2 (`v2-t10-ttl10`), oracle (direct during the delay, inline otherwise).
- **Scenarios:** `stationary` (no delay: measures the cost of adapting when nothing changes) and `inline-degraded`.
- **Measures:** H2c′ — v2 has fewer misses than frozen in the delay phase and uses fewer tokens. Secondary: reaction and recovery lag (RQ3), probes and switches, v2 against v1 (RQ4), pass rate. Fixed direct is reported next to the primary contrast: over a whole episode it has few misses at a fifth of the tokens, so the claim is "feedback beats a router without feedback", not "adaptation beats every fixed choice".
- **Evidence so far:** replay — frozen 28.4 misses per episode, v2 12.6, oracle 3.6; pilot P3′ (live, 48 requests) — delay-phase misses v2 5 against frozen 14, recovery lag 2, tokens 452k against 774k.
- **Status:** collected 2026-10-15 (60 episodes, seeds 301–305, 5,760 requests). H2c′ supported: delay-phase misses v2 8.6 against frozen 27.2 per episode, tokens 1,065k against 1,490k; results in the pre-registration ("S-E′ collection record").
- **Files:** `examples/studies/study.seams3-inline-degradation.json`, `examples/studies/pilot.v3-inline-degradation.json`, `studies/replay-v3calib/inline-degradation.json`.

### P3 — the same scenario with MCP lean as the fallback (pilot, "before")

- **Question:** what happens when the fallback cannot meet the deadline?
- **Setup:** v2 catalogue (inline and MCP lean), limit 10 s, inline +9 s.
- **Evidence:** live pilot — v2 reacted (lag 2) but lean missed 10 s most of the time; delay-phase misses 11 against frozen's 14, recovery lag 9, whole episode 15 against 14.
- **Use:** with P3′, the same controller succeeds or fails depending on whether a feasible fallback exists (condition C3). Pilot data, labelled as such, never pooled.

### S-B′ — token quota throttles inline (replay only)

- **Question:** can feedback handle a disturbance its own actions cause? A tokens-per-minute quota makes requests wait when recent consumption is high; inline (16k tokens per request) triggers it, direct (3k) does not.
- **Setup:** inline and direct, limit 7 s, quota 60k tokens per minute during requests 31–60.
- **Evidence:** replay — frozen 9.9 misses, v2 9.0, best oracle 3.7 (capture 15 %). A trace (`tools/seams/quota_attribution.py`) shows why: the stalls are bursty, so inline still looks acceptable most of the time, and waits caused by inline's consumption land on direct requests too. The monitor blames a shared, self-inflicted disturbance on whichever configuration runs next.
- **Use:** discussion of a monitoring limitation (separate queueing from service time). Not collected live: the predicted effect is too small for 3–5 seeds.

### S-F — direct degrades (replay only, negative)

- **Question:** can feedback move away from a cheap, good incumbent when it degrades?
- **Setup:** inline, direct and lean, limit 8 s, direct's tool calls delayed 1–3 s.
- **Evidence:** the selection rule fails closed. In normal conditions every v2 candidate spends 0.72–0.85M tokens per episode against frozen's 0.37M, because it keeps probing inline, which costs about 5× a direct request.
- **Use:** negative case for condition C5 (cheap probing): adaptation does not pay off when the incumbent is far cheaper than any alternative.

### Round-trip slowdown (replay only)

- **Question:** how exposed is each surface to a provider-wide slowdown per model call?
- **Setup:** the same tool-call delay (1–3 s) on direct and lean; inline unaffected.
- **Evidence:** at 10 s and +2 s per call, fixed direct misses 3.6 per episode, fixed lean 30.8. At mild points v2 misses more than frozen: reacting to a disturbance the incumbent can absorb costs more than it saves.
- **Use:** a figure linking interface design and adaptation: fewer calls per request means less exposure.

### S-D — lean-first cascade (not collected)

- **Question:** can a within-request fallback (lean, then default after a failure) repair a fragile surface?
- **Evidence:** pilot P1 (live) — 0 final failures, every fallback triggered by a step-limit error, but 1.48× the tokens of MCP default; the v1 held-out counterfactual — 100 % pass at ≥ 8.8k against 13.7k tokens per request.
- **Use:** secondary, exploratory result. The direct surface removes the failures the cascade repairs, which weakens its motivation.

### Earlier negative cases (replay only)

- **v2 S-A (MCP lean degrades, inline fallback):** superseded by v3; MCP default had drifted too slow for the original rule.
- **Function lean as the cheap configuration:** exploration too expensive.
- **Token cap:** token cost is predictable from request size, so a static per-size rule matches feedback (condition C2 fails).
- **Transport faults (MCP vs functions):** no advantage for adaptation.

## How replay works

1. The frozen baseline holds real calibration measurements (latency, tokens, pass, tool calls) per configuration and size bin.
2. A simulated request draws one of those measurements for the chosen configuration at random.
3. Disturbances are applied arithmetically: a request delay adds its value; a tool-call delay adds its value × the recorded tool calls; a quota adds waits on a simulated clock.
4. The real controller code (`Controller.decide` / `observe`) chooses each request's configuration and sees the simulated outcome.
5. Seeds × replicates give means per policy and grid point.

```bash
llmctxbench study replay --baseline baselines/repoqa-long64-v3/frozen.json \
  --grid examples/studies/replay/v3-inline-degradation.grid.json --output studies/replay-v3calib/inline-degradation.json
```

### Replay against live (validation, 2026-10-15)

Each pilot definition was replayed exactly (50 replicates) and compared with the live
pilot (one episode per arm). Misses per 48-request episode:

| Pilot | inline or fixed | frozen | v1 | v2 |
|---|---|---|---|---|
| P2 replay / live | 13.9 / 12 | 7.5 / 8 | 8.3 / 13 | 4.6 / 6 |
| P3 replay / live | 16.0 / 16 | 14.7 / 14 | 11.0 / 11 | 8.8 / 15 |
| P3′ replay / live | 16.1 / 16 | 14.6 / 15 | 6.9 / 10 | 7.1 / 5 |

- Fixed arms and the frozen router are predicted within about 1–2 misses; tokens are 2–10 % low.
- Adaptive routers deviate by 2–6 misses in both directions; in P3 replay was optimistic about v2.
- Causes: single live episodes are noisy; replay draws requests independently, while real providers have slow periods that correlate consecutive requests; replay draws from 4 calibration targets only; it does not model the model reacting to a slow tool.

**Use in the paper:** replay selects parameters and maps where adaptation could pay off
(RQ1); its outputs are labelled `estimated`. Claims about adaptive behaviour rest on live
episodes. The validation table belongs in the threats to validity.

## Where each research question gets its evidence

| Question | Evidence |
|---|---|
| RQ1: when does adaptation pay off? | replay map (S-E′ positive; S-B′ low capture; S-F exploration cost; round-trip; earlier negatives); P3 against P3′ live |
| RQ2: does feedback reduce misses and cost? | S-E′ live, 5 seeds, target-cluster bootstrap intervals |
| RQ3: how fast, at what cost? | S-E′ lags, probes, switches, controller overhead |
| RQ4: which design choices matter? | v1 against v2 in S-E′; replay ablations; v1 lessons |
| Secondary | cascade (P1, counterfactual); interface redesign (direct surface) |

## Figures and tables

Generated without provider calls from the v3 baseline, the replay reports, the pilots and
the S-E′ study; run from the repository root:

```bash
python tools/seams/quota_attribution.py > /dev/null   # writes studies/replay-v3calib/quota-attribution.json
llmctxbench study replay --baseline baselines/repoqa-long64-v3/frozen.json \
  --grid examples/studies/replay/v3-limit-sweep.grid.json --output studies/replay-v3calib/limit-sweep.json
python tools/seams/make_figures.py                   # docs/seams2027/figures/*.pdf
python tools/seams/make_tables.py                    # docs/seams2027/tables/*.tex (booktabs)
```

| Output | Content |
|---|---|
| `figures/replay-opportunity.pdf` | replay map: opportunity (frozen − oracle) against what v2 recovers, for S-E′, S-B′, S-F, round-trip |
| `figures/se-timeline.pdf` | S-E′ live: miss rate and share routed to direct per request position |
| `figures/se-tradeoff.pdf` | S-E′ live: tokens against misses per arm, stationary and degraded, seed ranges |
| `figures/pilots-p3.pdf` | P3 (lean fallback) against P3′ (direct fallback), misses per phase |
| `figures/replay-round-trip.pdf` | replay: misses against per-call delay for each surface |
| `figures/deadline-origin.pdf` | calibration latency per configuration and size bin, with p90 and the candidate limits (how 7 s was chosen) |
| `figures/se-requests.pdf` | S-E′ live, seed 301: every request of fixed inline, frozen, v2 and fixed direct (configuration, size bin, misses, probes) |
| `figures/replay-limit-sweep.pdf` | replay: S-E′ arms across limits 5–10 s, without and with the delay and summed; live S-E′ means at 7 s (exploratory, after collection) |
| `figures/replay-quota-attribution.pdf` | replay S-B′: quota-phase misses by configuration and quota wait |
| `tables/catalogue.tex` | v3 calibration catalogue |
| `tables/se-results.tex`, `tables/se-contrasts.tex` | S-E′ live results and delay-phase intervals |
| `tables/validation.tex` | replay against live |
| `tables/ablation.tex` | replay ablation of v2 design choices at the S-E′ point |

## Limits

One task (search needle function), one model (gpt-6-luna), 16 held-out targets reused
from v1, injected disturbances, a local MCP server (no network), and parameters selected
on 4 calibration targets.
