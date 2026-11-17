# WP-H implementation report: metrics, goals, summarize, and headroom

**Status:** implementation complete; acceptance review pending.

WP-H adds request-record-based adaptive goal evaluation, the `adaptive_goal_metrics.csv` output,
signal and provenance columns in adaptive attempt metrics, adaptive run summaries, and benchmark
headroom analysis. `ctxbench.api` now exports `summarize` and `headroom`. The goal evaluator uses
the existing observation-window implementation and includes each terminal request in its own
goal reading. The analysis functions read recorded artifacts and do not invoke providers.

## Changes

- `adaptive/goals.py` evaluates upper and lower bounds as `met`, `violated`, or `unknown` from
  terminal request observations.
- Adaptive metrics now include dynamic request-label columns, policy identity, failure category,
  built-in and declared signal values with provenance, accepted status, disturbance effects, and
  a goal table. Obsolete fallback metrics columns were removed.
- `analysis/summarize.py` emits one flat summary mapping per adaptive run, including the digest of
  the ordered frozen request list, delivery and failure counts, signal aggregates for all terminal
  attempts and delivered requests, and per-goal violation counts.
- `analysis/headroom.py` compares a benchmark's best static candidate and per-request oracle over
  cells with complete candidate coverage. It reports oracle-win shares, missing-cell coverage,
  optional feature groups, derived provenance, and the interpretation limits from the design.
- `ctxbench.api` exports both analysis functions. Adaptive metrics manifests list the new goal
  output.

## Validation

`pytest -q` — 605 passed. `git diff --check` passed. No provider workflows were run. The API
lifecycle assertion now includes the `goals` table and its zero-row count when the experiment has
no declared goals.

## Acceptance gates for review

- Goal statuses match hand-computed sliding and fixed windows, including whole-run windows and
  unknown readings, using request records alone.
- Generation, assessor, and evaluation usage remain in separate metrics columns.
- Run summaries report workload digest and distinct all-attempt and delivered-request views.
- Headroom reproduces hand-computed static/oracle totals and exposes missing matrix cells.
- Existing benchmark metrics and artifacts remain unchanged.
