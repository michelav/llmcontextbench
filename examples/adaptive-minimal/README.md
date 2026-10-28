# Minimal adaptive example

This provider-free example exercises the adaptive plan and request lifecycle with one explicit
request and a static controller. Run `llmctxbench plan examples/adaptive-minimal/experiment.json`,
then `llmctxbench execute` from the generated output directory. The selected attempt is available
to the normal `eval`, `export`, `metrics`, and `status` commands. Threshold definitions use a
separate completed static run without evaluation as `adaptation.calibration`; calibration and
adaptive workload requests may not overlap.

For bounded same-request fallback, use a `cascade` policy with a `candidate` and optional `fallbacks`
array of candidate pairs. `minimumResponseLength` enables the local response acceptance sensor; zero
or omission accepts any successful nonempty or empty response. Request records distinguish delivery
from execution success and retain attempt-level usage, cumulative request usage, and sensor cost.

The adaptive v1 schema also accepts `utility`, `circuit_breaker`, `budget`, and `explore` policies.
The estimate-driven policies use calibration data. `budget.bestEffort` allows dispatch when prior or
candidate token usage is unknown or the estimate exceeds the remaining budget. An optional
`tokenQuota` enforces a rolling token window and restores usage from saved attempt timestamps; strict
quota mode stops on unknown usage. A phase may set `toolFailureRate` with an integer `failureSeed` to
inject deterministic tool-call failures for provider-free disturbance studies.
