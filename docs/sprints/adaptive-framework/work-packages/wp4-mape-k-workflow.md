# WP4 implementation record: adaptive MAPE-K workflow

The version 2 typed adaptive workflow in `ctxbench.adaptive.workflow` consumes ordered
request occurrences and declared candidate invocations built from the workflow-neutral
`ExecutionRequest`. It does not accept or construct benchmark `TrialSpec` objects. Candidate
IDs and execution IDs are validated against the frozen workflow and request identity.

For each request, Plan persists a decision before calling `TrialExecutionService`. Execute
uses the same run-scoped `ExecutionSession`; Monitor records runtime metrics, the typed
response-acceptance sensor, and an optional declared online quality assessor; Analyze checks
execution success and every declared latency, token, acceptance, and quality SLO. Missing
quality values are recorded as unavailable and cannot satisfy an SLO. A failed acceptance
or SLO leads to another persisted Plan decision from the remaining eligible candidates.

`adaptive-records/{requestId}.json` is the per-request ledger. It stores decisions, admission
inputs and outcomes, observations, SLO analysis, delivery identity, and post-observation
Knowledge snapshots. The shared execution records remain authoritative for invocation
outcomes. Online sensor outputs are persisted with the invocation result so recovery after
execution completion does not rerun the assessor or lose its cost and provenance.

Resume processes requests in frozen sequence order. It replays saved decisions and only
rebuilds Knowledge from calibration plus observations in the earlier request prefix and the
current request's earlier attempts. Records for later requests are validated but never used
to choose or admit an earlier attempt. Calibration uses WP2's provenance contract and must
match the dataset, candidate catalog, feature schema, estimator definition, and disjoint
source request IDs.

Adaptive plan creation from public definitions and complete CLI dispatch remain in WP6.
The current execute command explicitly rejects adaptive plan schema version 1; it does not
migrate or run that legacy plan.
