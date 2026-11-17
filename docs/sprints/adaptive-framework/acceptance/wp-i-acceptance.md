# WP-I implementation report: documentation reorganisation, examples, cleanup

**Status:** implementation complete; acceptance review pending.

WP-I reorganises the documentation into `guide/` (current behaviour), `architecture/` (current
design), `development/` and `sprints/` (history), promotes the adaptive-framework design into
architecture documents and ADRs, writes the user guide and references, and makes the
documentation gate executable.

## Changes

- **Layout and rules.** Documents moved with `git mv` (relative links rewritten).
  `docs/README.md` states where each kind of content goes. Sprint folders have semantic names
  (`v1-refactor`, `runtime-extraction`, `evolution-plan`, `metrics-command`,
  `adaptive-framework`); dates are in `sprints/README.md` and each sprint README. Spec-kit
  prompts moved to `.specify/prompts/spec-kit/`.
- **Architecture.** `contracts/adaptive-plan.md` (plan v4, replacing `adaptive-plan-v3.md`),
  `contracts/manifest.md` and `contracts/records.md` were written from the code, not only from
  the design. `workflows/workflow-contract.md` (merged with the former `workflow.md`),
  `workflows/benchmark.md` and `workflows/adaptive.md` carry the normative workflow content.
  `vocabulary.md` became `domain-model.md` with the adaptive terms. The original metrics
  specification moved to `sprints/metrics-command/`; `architecture/metrics-design.md` keeps the
  current rules. ADRs 0001–0006 record the durable decisions and link to the sprint material.
- **Guide.** Getting started, concepts, benchmark and adaptive experiments, experiments in code,
  and references for the CLI, both definition schemas, the Python API, output artifacts and every
  metric column with its provenance class. The README is reduced to an overview, install,
  quickstart and links; development content moved to `docs/development/README.md`.
- **Examples.** The fake dataset is copied to `examples/datasets/fake/` and the examples point
  at it. New `examples/adaptive/window-threshold.json` (generated workload, two candidates, a
  token budget per fixed window, a goal, a model disturbance). `code_built.py` now executes the
  run and writes metrics. `examples/adaptive/README.md` is replaced by the guide.
- **Gate.** `tests/test_docs.py` runs every command in `console` blocks of `README.md` and
  `docs/guide/` in a temporary copy of `examples/` (refusing any `plan` of a definition with a
  non-mock model or judge), fails on unmarked `shell` blocks that run `llmctxbench`, checks every
  relative link in `README.md` and `docs/`, checks that the metrics reference names every emitted
  column, and checks that `guide/` and `architecture/` do not refer to work packages.
- **Cleanup.** `demo-video.md` folded into the README; the empty example folders were untracked
  and are gone.

## Deviations

- **Re-exports kept.** Every compatibility re-export left by earlier moves still has callers
  (`benchmark/fingerprint.py`, `benchmark/surfaces.py`, `resolve_definition` through
  `benchmark.definitions`, `DatasetProvenance` through `benchmark.models`, including imports from
  `dataset/` and the adapters). Removing them needs caller migration, which is a refactor outside
  this package.
- **`eval` is not documented as runnable.** The mock provider does not return judge JSON (tests
  fake the judge), so `eval` is shown in skip-marked blocks and the examples disable evaluation.
- **API re-exports.** `ctxbench.api` exports `Policy`, `Decision`, `CandidateRef` and
  `PolicyContractError`, but not `SystemState`, `Reading` or `CandidateState`; the guide
  documents what is exported.

## Validation

```text
pytest tests/test_docs.py -q     133 passed, 11 skipped (pages without console blocks)
pytest -q                        754 passed, 11 skipped
```

The documented custom policy in `guide/adaptive-experiments.md` was run as an external plug-in
with `--plugin-path` against `window-threshold.json`. No real provider was called.
