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

## Review fixes

- **Fixed-window goals.** Goal evaluation offset the window by one request, so the last request
  of each fixed block read an empty window (value 0, `met`). `WindowSystemState` now takes
  `through_current=True` for goal evaluation only: the window includes the evaluated request and
  keeps its block. Policy decisions are unchanged.
- **Run arguments.** `summarize` and `headroom` mistook a `pathlib.Path` for a run handle
  (`Path.root` is the filesystem root). `ctxbench.analysis.run_root` accepts strings, paths and
  `Run` handles and refuses anything else.
- **`accepted` column.** The `accepted` signal no longer overwrites the boolean `accepted`
  attempt column; its provenance stays in `acceptedProvenance`.
- **All-attempt view.** `summarize` builds `allAttempts` from every execution attempt record
  (`metrics.adaptive.load_execution_attempts`), including attempts of requests that never became
  terminal; an attempt without a result counts as missing. It also reports `attempts`.
- **Import boundary.** Section 3 now lets `analysis` import the read-only artifact readers
  `adaptive.artifacts` and `metrics.adaptive`; `tests/test_import_boundaries.py` enforces the
  allowed set for `analysis`. The `metrics` row records its existing exceptions and is not yet
  enforced.

## Acceptance checks

| Gate | Test (`tests/test_adaptive_analysis.py` unless noted) |
|---|---|
| Goal statuses match hand-computed fixed windows | `test_goal_fixed_window_includes_each_request_and_resets_per_block` |
| … sliding windows | `test_goal_sliding_window_is_the_last_n_requests_ending_with_each_request` |
| … whole-run window, lower bound, experiment default window | `test_goal_whole_run_window_and_lower_bound`, `test_goal_uses_the_experiment_window_by_default` |
| Unavailable reading is `unknown`; non-terminal requests are skipped | `test_goal_with_unavailable_reading_is_unknown_not_met`, `test_goal_ignores_requests_that_are_not_terminal` |
| Goal table reproducible from the plan and request records alone | `test_goal_table_is_reproducible_from_request_records_alone` |
| Generation, assessor and evaluation usage in separate columns; signal columns; `accepted` stays boolean | `test_attempt_metrics_keep_usage_views_separate_and_accepted_boolean` |
| `summarize`: workload digest, separate all-attempt and delivered views, provenance, goal violations | `test_summarize_reports_workload_digest_and_separate_cost_views`, `test_summarize_digest_compares_workloads_not_policies` |
| `summarize` counts attempts of non-terminal requests | `test_summarize_counts_attempts_of_requests_that_never_became_terminal` |
| `headroom` reproduces hand-computed values and reports missing cells | `test_headroom_reproduces_hand_computed_minimum`, `test_headroom_reproduces_hand_computed_maximum_and_groups` |
| Analysis accepts paths, strings and run handles; headroom refuses adaptive runs | `test_analysis_accepts_paths_strings_and_run_handles`, `test_headroom_refuses_adaptive_runs` |
| `analysis` imports only allowed modules | `tests/test_import_boundaries.py::test_import_boundary_analysis_reads_artifacts_only` |

Validation: `pytest -q tests` — 621 passed. No real-provider execution or evaluation was run.

## Known limitations

- `headroom(by=...)` groups by trial fields, `parameters` or `taskTags`, not by dataset request
  features as section 9.5 states; a feature that is not also a trial field groups as `<missing>`.
- `headroom` counts a candidate's failed cells as missing; failed and missing are not reported
  separately.
- Attempt rows carry built-in token signals under both the existing camelCase columns and the
  signal names (`totalTokens` and `total_tokens`).
- The `unmetConditions` request column was removed along with the fallback columns; it was always
  empty.
