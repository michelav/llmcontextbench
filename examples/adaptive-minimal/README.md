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
