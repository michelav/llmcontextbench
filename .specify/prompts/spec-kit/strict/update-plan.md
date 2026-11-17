# Update plan

Use this when the technical approach, affected files, migration strategy, or validation changed.

```text
Update {{SPEC_DIR}}/plan.md based on the current spec.md.

Do not update spec.md unless you find a contradiction; report contradictions separately.
Do not update tasks.md yet.
Do not implement code.
Do not run provider-backed commands.

Incorporate this discovery or design change:

{{DISCOVERY}}

The updated plan must cover, when relevant:

- affected source files;
- affected tests;
- artifact reader/writer behavior;
- compatibility behavior;
- migration strategy;
- fixture-based validation;
- documentation updates;
- risks;
- Constitution Check status.

Preserve the simplest design that satisfies the spec.
Avoid adding schema registries, plugin frameworks, metadata layers, or broad rewrites unless required by the spec.

After editing, report:

- plan sections changed;
- whether contracts/ or quickstart.md must change;
- whether tasks.md must be regenerated.
```
