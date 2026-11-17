# Plan specific spec

Use this with `/speckit.plan`.

```text
/speckit.plan

Plan only this specification:

{{SPEC_DIR}}/spec.md

Use this feature directory:

SPECIFY_FEATURE_DIRECTORY={{SPEC_DIR}}

Do not create or switch branches.
Do not implement code.
Do not run provider-backed commands.
Do not plan any other spec.

Generate or update the implementation plan and supporting artifacts in the same directory.

The plan must follow the current constitution and architecture docs.

Focus on:

- phase separation;
- artifact contracts;
- metric provenance;
- strategy comparability;
- domain/provider boundary isolation;
- migration expectations;
- provider-free validation;
- simplicity and research sufficiency;
- documentation impact.

The plan should produce, when useful:

- plan.md;
- research.md;
- data-model.md;
- contracts/;
- quickstart.md.

Stop after planning. Do not generate tasks unless explicitly requested.
```
