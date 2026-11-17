# Plan with slices

```text
/speckit.plan

Plan only this spec:

{{SPEC_DIR}}/spec.md

Use this feature directory:

SPECIFY_FEATURE_DIRECTORY={{SPEC_DIR}}

Use the current constitution and docs/architecture as constraints.

Create a concise plan with implementation slices.

Each slice must include:
- goal;
- likely files;
- focused validation;
- dependencies;
- suggested commit message.

Keep slices small and reviewable.
Do not generate tasks yet.
Do not implement code.
Do not run provider-backed commands.
```
