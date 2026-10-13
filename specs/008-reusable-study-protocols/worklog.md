# Worklog

## 2026-10-13 — Proposed design

Inspected current RepoQA workflow, calibration, policy state, runner/recovery,
sidecars, both local strategies, surface registration, tests and existing lean
surface plan. Created a Level 3 specification and dependency-ordered implementation
slices for reusable baselines and declarative studies. No implementation, provider
execution, artifact migration, or dependency changes. Scientific thresholds and
live collection authorization remain future decisions. Formal plan review and
focused task generation follow design acceptance.

## 2026-10-13 — Simplicity review

Removed seed aliases, named episode groups, duplicate study inputs, standalone
calibration snapshots, authored digests/implementation versions, historical reuse
modes, collection merging, generic features/analysis and automatic delay calibration
from V1. Baselines define a stationary configuration × seed × repeat matrix; studies
inherit the frozen baseline and held-out partition. Keep plain integer seeds and
generate provenance automatically. Combined policies and repeated splits remain
future research. Replaced the ten-slice plan with six incremental deliveries.
No runtime implementation, artifact changes or provider execution.

## 2026-10-13 — MCP error propagation prerequisite

Added independently shippable slice 0 for the reproduced RepoQA MCP error-flag
loss, with protocol/runtime/strategy regression coverage and a separate Lattes
reproduction check. Recorded the 22 affected historical tool payloads and required
fresh compatible measurements after correction. This update changes planning only;
no runtime code, saved runs, or experiment configuration changed.

## 2026-10-13 — Slice 0 implementation

Preserved RepoQA operation error content and flags using FastMCP's result conversion
extension point. Success serialization is unchanged. Lattes missing-data reproduction
raises in the service, so no equivalent flag-loss fix was applied there. Added actual
MCP runtime and strategy recovery tests; historical runs remain untouched.

## 2026-10-13 — Slice 1 implementation and bounded audit

Added opt-in lean operations to both transports, preserving default catalogs and
verbose behavior. Lean schemas/results match through the actual MCP runtime.
47 operation/surface tests pass; slice 0 runtime/strategy suite passed 28 tests.
Added `experiment.repoqa-five.json` without modifying existing experiment files.

Audit command: `.venv/bin/python tools/analysis/audit_operation_failures.py runs/repoqa-adaptive-001`.
Streamed 30 response files (11,457,423 bytes), inspected one referenced trace at a
time. Counts reconcile: 1,728 responses = 1,667 successes + 61 failures; all 61
terminal failures explicitly report max_steps=8, unknown=0. Separately, 22 error-only
operation payloads carry false flags. Neither observation demonstrates a transport
reliability disadvantage. No historical files were changed.

## 2026-10-13 — Reusable protocol implementation

Implemented V3 baseline and study schemas, prepared/frozen artifacts, deterministic
split and workload matrices, fixed and adaptive multi-candidate controllers,
request and tool-call latency treatments, budget and reliability policies,
recovery packets, CLI, fixture tests, examples and protocol documentation.
The new path is separate from legacy adaptation commands and canonical artifact
schemas. Provider-backed collection/evaluation was not run. Full regression and
research audit findings follow validation.

## 2026-10-13 — Validation and research audit

Provider-free regression: `.venv/bin/pytest -q -x tests/test_mcp_operation_errors.py tests/test_repoqa_lean.py tests/test_repoqa_surfaces.py tests/test_repoqa_tools.py tests/test_adaptive_runner.py tests/test_adaptive_policy.py tests/test_adaptive_token_accounting.py tests/test_adaptive_calibration.py tests/test_repoqa_workflow.py tests/test_repoqa_study.py tests/test_repoqa_output_configurations.py tests/test_repoqa_evaluation.py tests/test_study_baseline.py tests/test_study_protocol.py tests/test_cli.py`: 248 passed. Follow-up measurement fingerprint check: 2 passed. Standard deterministic RepoQA evaluation, export and metrics were exercised on a fixture episode. The five-configuration example prepared 30 episodes with 4 calibration and 16 held-out targets; all 80 instances passed initial context-fit preflight under its stated 131072-token context limit.

No real answering or judge provider calls were made. Historical runs and canonical artifact schemas were not rewritten. The saved historical audit found 61 step-limit terminal failures and 22 error-only operation payloads with false flags, which do not establish a transport-specific reliability advantage. Adaptive benefit over fixed arms is unmeasured until separately authorized live collection. The narrow source fingerprint intentionally includes failure classification because changing that classification changes saved baseline evidence; study policy definitions and analysis do not invalidate measurements.
