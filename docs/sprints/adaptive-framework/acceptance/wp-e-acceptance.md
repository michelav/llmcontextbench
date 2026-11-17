# WP-E acceptance report: disturbances and scenarios

**Status:** accepted after two review rounds.

WP-E wires frozen disturbance definitions into adaptive execution. Definitions normalize through
`DisturbanceSpec`, and the canonical disturbance list remains in the adaptive plan payload, so it
is covered by the execution fingerprint. Each selected request and candidate receives only the
matching component interceptors. Tool and model wrappers report accumulated delay and injected
failure counts. Injected failures are tagged at the injection point with the category of a real
failure of their component (see Second review).

Model interception is per call through `Engine`; it does not mutate a shared engine or provider
adapter. Tool and model delays run inside the measured runtime interval. Applied effects are
persisted in `_adaptiveSignals.disturbances` with the durable execution result and copied to the
adaptive attempt record, so resume reuses the recorded outcome.

Validation covered sequence and candidate scoping, deterministic seeded outcomes, model delay and
failure handling, fingerprint sensitivity, failure classification, latency accounting, and
durable effect recording. No real providers were used.

## Review fixes

- `plan` refuses a disturbance that could never apply: a duplicate name, a tool component that a
  named candidate (or, without `candidates`, any candidate) does not use, or a `firstSequence`
  after the last request.
- Failure draws hash the disturbance name, seed, sequence index, call index and operation as
  separate fields. Before, `seed + sequence` made disturbances with nearby seeds draw shifted
  copies of each other. Draws differ from those of the first WP-E version.
- `delayMs` is an integer in the definition schema, as `DisturbanceSpec` requires.
- The design (§6.12) now states the three kinds, that effects are per call, the provenance of
  `appliedDelayMs`, and that model interception sits outside provider rate control.
- Tests added in `tests/test_adaptive_disturbances.py`: tool components (counters, injected
  failure category through the engine), requests and candidates outside the declared scope, two
  whole runs with equal seed, and resume after an interruption between the durable writes.

Checks:

- `pytest -q tests/test_adaptive_disturbances.py tests/test_adaptive_contracts.py tests/test_adaptive_workflow.py tests/test_adaptive_signals_state.py` — 83 passed.
- `pytest -q` — 516 passed.

No artifact version change was needed: the active adaptive plan, execution result, and record
versions already include the fields needed for this WP.

## Second review

- Policies can no longer tell injected failures from real ones. An injected failure takes the
  category a real failure of its component gets: `tool_error` for a tool component,
  `provider_error` for `model`. `injected_disturbance` is removed from the failure categories, so
  `failed.injected_disturbance` is an unknown signal, refused at `plan` and by `state.window()`.
  The injection stays auditable in the attempt's `disturbances` entry and the trace error message.
  Failure categories of disturbed runs made before this change differ.
- `Engine` checks capabilities on the resolved adapter before applying the model interceptor. A
  capability error names the adapter, and an attempt refused for capability makes no model call
  and records no model disturbance entry.
- Tool and model wrappers share one base (`_SeededDisturbance`) for argument checks, delay,
  failure draw and effect record. The model wrapper now refuses invalid arguments as the tool
  wrapper does; both require an integer delay.
- Tests added: tool delay inside measured runtime latency and reported separately; capability
  check sees the adapter; wrapper argument checks; `failed.injected_disturbance` refused.

Checks:

- `pytest -q tests/test_adaptive_disturbances.py tests/test_adaptive_contracts.py tests/test_adaptive_workflow.py tests/test_adaptive_signals_state.py` — 100 passed.
- `pytest -q` — 533 passed.
