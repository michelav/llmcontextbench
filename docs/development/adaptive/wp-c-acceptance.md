# WP-C acceptance: signals, state, and built-in policies

**Status:** implemented; awaiting review before WP-E, WP-F, WP-G, or WP-H.

## Delivered

- Added typed adaptive signal values, extraction with provenance, partial token subtotals, and
  normalized failure categories. The mock provider can report a context limit failure; provider
  error classification covers the four model providers in the repository.
- Persisted signal maps and failure categories in terminal request observations. Resume rebuilds
  the prefix observation log from those records.
- Added system and candidate windows, sliding/fixed/all selection, statistics, capacity-derived
  readings, and per-decision reading audits.
- Added `window_threshold` and `min_signal`, including early validation, deterministic declared
  order behavior, unavailable handling, per-policy candidate target declarations, and reading
  audit persistence.
- Added an additive `category` field to engine error trace metadata. Existing benchmark artifact
  schemas and versions are unchanged.
- Persisted the complete `_adaptiveSignals` payload with the execution result; recovery after the
  execution/request-record write boundary copies that payload without re-executing or extracting
  the signals again. Moved the state protocol and candidate state types into `adaptive/state.py`.

## Acceptance checks

- Focused checks: `107 passed` (`pytest -q tests/test_adaptive_signals_state.py
  tests/test_adaptive_workflow.py tests/test_ai.py tests/test_import_boundaries.py`).
- Full provider-free suite: `481 passed` (`pytest -q`).
- Tests cover every statistic, missing and partial values, provenance, capacity, scopes, fixed
  windows, tier boundaries, `min_signal` exploration and ties, context-overflow classification,
  prefix-causal resume, and replay of persisted readings.
- Mock context overflow stays one attempt, records measured duration and unavailable token usage,
  and is visible to the next policy as `failed.context_overflow`.
- Engine error traces include a normalized category, and unrecognized provider errors map to
  `provider_error`.
- `git diff --check` is clean. No real provider execution or evaluation was run.

## Review fixes

- A context overflow whose message contains the digits "429" is no longer classified as a rate
  limit; a recognised overflow is fatal and is not retried.
- `min_signal` explores by observation count, so it cannot lock onto a candidate whose signal is
  never available.
- The system state no longer stores the decision ID (which embeds the request ID) or the seed.
- `model_calls` and `tool_calls` are unavailable, not zero, when no metrics summary exists.
- The failure category is assigned where the failure happens (`ai/failures.py`) and carried in the
  adaptive attempt result as `failureCategory`; nothing is inferred from error text.

## Known deviations from the design (open)

- Each `readings` entry nests a `reading` object; `knownSubtotal` is stored inside each signal.
- Context-overflow markers are one table in `ai/rate_control.py`, not code inside each adapter.
- `_validate_signal_policy` validates signal and statistic by built-in policy name.

## Scope boundary

Online quality assessors remain in WP-F. Goals and summaries remain in WP-H. Scenario disturbances
remain in WP-E.
