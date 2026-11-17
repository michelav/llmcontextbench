# Convert spec to lite format

Use this prompt after reviewing an existing spec and deciding that it can be simplified.

```text
Convert this existing spec to the lightweight spec format:

{{SPEC_DIR}}/spec.md

Use the current spec as source of truth.

Do not implement code.
Do not run provider-backed commands.
Do not change the feature intent.
Do not remove accepted requirements, accepted scope, or accepted migration decisions.
Do not move implementation details into the spec unless they define a public contract.

Rewrite the spec using this structure:

- Goal
- Scope
- Out of Scope
- Requirements
- Acceptance Scenarios using Given/When/Then
- Impact
- Compatibility / Migration
- Validation
- Dependencies
- Risks
- Open Questions

Preserve:
- all accepted functional requirements;
- compatibility/migration decisions;
- artifact, metric, dataset, provider, and documentation impacts;
- explicitly accepted non-goals;
- open questions that still matter.

Compress or remove:
- generic product/app boilerplate;
- duplicated explanation;
- plan-level implementation details;
- task-level details;
- obsolete alternatives;
- verbose user-story text that can become concise acceptance scenarios.

After editing, report:
- what was preserved;
- what was removed or compressed;
- any decision that needs human review;
- whether plan.md or tasks.md need updates.
```
