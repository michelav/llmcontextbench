# LLMCtxBench v1 worklog

## S01 — complete

- Created `refactor/llmctxbench-v1` from `r3`; existing untracked research data preserved.
- Replaced superseded draft with accepted simple design; added slice checklist and specification.
- Architecture distinguishes implemented baseline from target behavior.
- Historical freeze tags found; Zenodo reference not present locally and requested from owner.
- No provider calls or dependency changes.

- Validation: local links checked in five primary documents; `git diff --check` passed.
- Tests not run: documentation-only slice, no runtime changes.
- Impact: accepted target is explicit, while existing architecture pages remain clearly labelled as the current baseline.
- Commit: `docs: establish tracked v1 refactor plan` (see branch history).

## S02 — complete

- Added version-3 definition validation with taskParams, modelParams, explicit candidate pairs,
  separate execution.options, inheritance and a published JSON Schema.
- Candidate planning preserves the selected pairs rather than creating an unintended cross product.
- Judge references retain generation parameters; dataset task substitutions retain their meaning.
- Transitional implementation: definition input is normalized once into the existing planner models;
  persisted trial field names migrate with readers/writers in S03/S06. Unversioned definitions remain
  for the existing study stack until S12; no new historical artifact reader was added.
- Validation: 45 focused definition/provisioning/schema/fake-dataset tests passed; diff check passed.
- Impact: v1 definitions are usable without replacing the runtime or altering existing study inputs.
- Commit: `refactor: clarify experiment configuration contracts`.

## S03 — complete

- Versioned plans freeze resolved.json and trials.jsonl with content hashes, implementation/dependency
  fingerprint and dataset digest. Full-length trial IDs use design keys. Execution verifies the
  fingerprint; artifact-only readers verify snapshot integrity without accessing the dataset.
- Cross-directory validation rejects conflicting fingerprints for an experiment identity.
- Transitional boundary: version-2 artifacts remain supported only by the existing stack until S12;
  version-3 artifacts require the frozen fingerprint. Public trial field migration remains in S06.
- Validation: 33 focused planning/definition/provisioning tests passed, including source edit,
  implementation edit, dataset edit, tampered snapshot and unknown-version cases. Diff check passed.
- Impact: editing a definition cannot change a saved execution; code/data changes require replanning.
- Commit: `feat: freeze execution inputs and validate identity`.
