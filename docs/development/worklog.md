# RepoQA prototype development log

## 2026-10-02 — Complete prototype slices 1 and 2

Accepted implementation plan: four internal slices A–D, scoped to surface
validation, model-free policies and sidecar contracts. Prototype semantics were
updated before implementation. The repository's existing unrelated changes were
preserved. Token usage provenance: unavailable.

- **A — Surface enforcement completed:** planning rejects empty/unknown operation
  lists; every operation is discovered and invoked through FastMCP; all omitted
  operations reject direct and transport calls. Artifact spying covers all four
  operations and excludes oracle/native-task/hidden-prompt/raw inputs.
  Focused surface/tool validation: **40 passed**. Adapter changes were unnecessary.
- **B — Contracts completed:** centralized canonical configuration IDs; explicit
  nominal variant mapping in RepoQA workload preparation; validated features,
  metrics, context-fit budgets/provenance and unique candidate IDs. Added versioned
  camelCase decision and run sidecars with identity/outcome metadata outside
  policy inputs. Sidecars are models only, without writers.
- **C — Estimation completed:** observe() belongs to policy arms; frozen/fixed
  arms record without updating. A shared estimator rejects mixed keys, computes
  rolling successful means, retains source provenance/counts, and independently
  applies the three-sample latency/token threshold with calibration fallback.
  Each state copies calibration and starts fresh. No time-based expiry.
- **D — Routing completed:** objective priority after cooldown, k+6 switching,
  exact 10% material improvement, known-before-missing ordering, canonical ties,
  ineligibility override, explicit unserved fixed arms, and transient probes that
  commit normal routing state. Policy version **2** is the documented baseline
  to pin before future calibration. Deterministic tests cover these branches.

Validation commands:

```bash
pytest -q tests/test_repoqa_surfaces.py tests/test_repoqa_tools.py
pytest -q tests/test_adaptive_policy.py
pytest -q tests/test_repoqa_surfaces.py tests/test_repoqa_tools.py \
  tests/test_adaptive_policy.py tests/test_provisioning_configurations.py \
  tests/test_artifact_contracts.py tests/test_dataset_provenance_artifacts.py \
  tests/test_util_artifacts.py
git diff --check
```

Final acceptance result: **127 passed**; whitespace validation passed.
The adaptive file contains 61 focused tests (including parameterized cases).
No provider execution/evaluation, dependency installation or lockfile changes.

Compatibility: CLI, canonical artifacts, RepoQA scoring and phase separation
remain unchanged; no artifact migration is needed. Internal ad hoc consumers
must supply explicit bins and context-fit assessments and replace caller-controlled
adaptive/evaluation flags with policy.observe(). Actual prompt/tool budgeting,
episode execution, delay injection, calibration and sidecar writing remain later
slices. Caller-provided context-fit estimates must remain traceable when those
components are integrated.

## Resumable A–E workflow implementation — 2026-10-08

Implemented reproducible catalogs/workloads, durable episode execution, replay and
uncertain-call recovery, controlled local-MCP delays, calibration/freeze operations,
and saved-episode analysis. See `repoqa-resumable-workflow.md` and
`specs/006-repoqa-adaptive-resume/` for the executable protocol and slice history.

Final targeted suite: **159 passed**, covering all four arms under both scenarios,
interruption/resume equivalence, terminal errors/unserved observations, canonical
artifact/evaluation compatibility, input drift/corruption/locking, calibration
qualification/provenance, token coverage, paired target bootstrap and interruption
sensitivity. Compilation and `git diff --check` passed. Real scorer smoke returned
best_match with similarity 1.0 after repairing an ignored local venv interpreter link.
No provider experiments, dependency installation or lockfile changes were performed.
Development token usage remains unavailable. Paid calibration and study gates remain
unexecuted; unknown prior expenditure after uncertain attempts is not imputed.
