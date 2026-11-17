# Promote spec to planning-ready

Use this when a lightweight spec exists and should be refined before `/speckit.plan`.

```text
Revise {{SPEC_DIR}}/spec.md.

Promote this lightweight specification into a planning-ready specification.

Do not implement code.
Do not create or switch branches.
Do not run provider-backed commands.

Make the specification testable and unambiguous enough for /speckit.plan.

Add or refine:

- prioritized user stories;
- functional requirements;
- acceptance scenarios;
- edge cases;
- assumptions;
- success criteria;
- key entities, if useful;
- explicit out-of-scope items;
- dependencies on previous specs;
- downstream specs enabled by this one;
- research and contract impact, when relevant.

Preserve the current intent:

{{FEATURE_GOAL}}

Preserve constitution constraints:

- phase separation;
- artifact contracts;
- metric provenance;
- strategy comparability;
- domain/provider boundary isolation;
- reproducibility and traceability;
- simplicity and research sufficiency.

Avoid implementation details unless required to define a public contract.

Report:

- changes made;
- remaining ambiguity;
- whether the spec is ready for planning.
```
