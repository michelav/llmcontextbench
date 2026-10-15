# Idea: task-oriented RepoQA tool interface (good vs bad interface design)

Status: **parked** (2026-10-15). Not part of the SEAMS 2027 pre-registered studies.
Revisit after SEAMS collection, or as a thesis chapter or follow-up paper.

## Motivation (evidence from v1 and v2 calibration)

Source: `tools/seams/interaction_patterns.py` on `baselines/repoqa-long64{,-v2}`; worklog
entry "why tool configurations are slower".

- Tool-configuration latency is almost entirely model time. Tools take about 10 ms per
  request and the harness about 30 ms.
- Tool configurations make about 3.9 sequential model calls per request; inline makes 1.
- **Per-call cost** (least squares, about 2,370 calls per run):
  - v1: 1.28 s fixed + about 0.01 s per 1k input tokens + 0.68 s per 100 output tokens (R² 0.55);
  - v2: 1.52 s fixed + about 0.01 s per 1k input tokens + 0.81 s per 100 output tokens (R² 0.45).

  Input size is nearly free and round trips are not. Latency is roughly the number of
  model calls times the cost per call.
- **The dominant pattern is a three-step navigation,** `list_files > list_symbols > get_symbol` → answer (62–83 % of requests):
  - `list_files` returns the same information for a repository every time;
  - parallel tool calls are allowed but rarely used (4–17 of 144 requests), because each step depends on the previous one.
- **The "lean" surface is lean only in payload size.** It has the same four operations and the same navigation.
  - Its median latency matches default.
  - Its tail (5–8 calls, 13–16 s) and its step-limit failures (`max_steps=8`; held-out `rs_004`, `py_005`) come from exploration loops (repeated `list_symbols`).
- **Provider slowdowns hit tool configurations harder.** A provider-wide increase in fixed cost affects them about 4 × more than inline (v1 → v2: +0.24 s per call ≈ +1 s per request).

## Candidate surfaces

Estimates use about 1.5 s per call plus about 0.8 s for the answer.

| Surface | Change | Model calls | Estimated latency |
|---|---|---|---|
| current lean | — | 3.9 (tail 5–8) | 7.4 s (p90 10–12 s) |
| `no-discovery` | file list in the system prompt, or `list_symbols` documented to search the whole repository when `path` is omitted | 3 | about 5.5 s (−25 %) |
| `direct` | one `find_symbol(workspace_id, description, k)` returning top-k candidates (name, path, signature, docstring, code) | 2 | about 3.8 s (−50 %; inline is 3.6 s) |
| `direct-terse` | as `direct`, returning IDs and signatures only, plus `get_symbol` for the chosen one | 3 | about 5.5 s, fewer tokens |

Design principles to test:
- remove calls that return information that doesn't depend on the question;
- one tool per task intent rather than per data structure;
- results rich enough to decide without a follow-up call;
- stable IDs;
- bounded result sizes.

## Expected effects and hypotheses

- **H-I1:** a task-oriented surface reduces model calls per request and latency (median and p90) without reducing pass rate.
- **H-I2:** it reduces the lean tail and the step-limit failures (fewer exploration loops).
- **H-I3:** it reduces sensitivity to provider-side per-call slowdowns, in proportion to the number of calls.
- **For runtime adaptation:** a good surface may dominate inline (similar latency, about 3–5 × fewer tokens), which removes stationary adaptation opportunities. Adaptation then matters only under disturbances. The point: catalogue quality determines whether runtime adaptation has anything to choose (RQ1 / C1).

## Constraints

- The surface code is fingerprinted by the frozen baselines: `src/ctxbench/adapters/repoqa/{tools,mcp_server,provider}.py`, plus the experiment configurations. Changing it in the main working tree blocks every study bound to `baselines/repoqa-long64-v2`.
- **Work in a separate git worktree or branch** until the SEAMS collection is complete. A new surface needs:
  - a new configuration in a new experiment file;
  - its own baseline if it is used in studies.
- Keep strategy logic separate from provider adapters; surface changes belong in the RepoQA adapter (dataset-specific).

## Minimal experiment (when revisited)

- **Arms:** inline, current lean (MCP), `no-discovery` (MCP), `direct` (MCP); optionally function-transport variants.
- **Workload:** the 16 held-out targets × 6 sizes × 1 repeat ≈ 96 requests per arm (about 400 requests, about 2–3M tokens). Use plain `llmctxbench plan/execute/eval`, not the study engine.
- **Metrics:**
  - pass rate;
  - model calls and steps per request;
  - latency median and p90;
  - input, output and cached tokens (separately);
  - step-limit failures;
  - tool-sequence distribution (`tools/seams/interaction_patterns.py` adapted for run directories).
- **Report:** per-call fit per arm, to separate "fewer calls" from "cheaper calls".

## Possible venues

- **SEAMS 2027:** at most one discussion paragraph or table (a design-time alternative to runtime adaptation), and only if the post-collection pilot fits the schedule.
- **Thesis:** a chapter on interface design for context provisioning (RepoQA and Lattes, MCP and functions).
- **Follow-up paper:** "good vs bad interfaces for LLM context tools" (empirical SE or LLM-agent venues).
