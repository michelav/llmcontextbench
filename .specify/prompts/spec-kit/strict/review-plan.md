# Review plan

Use this after `/speckit.plan` and before `/speckit.tasks`.

```text
Review {{SPEC_DIR}}/plan.md before task generation.

Do not edit files.
Do not implement code.
Do not run provider-backed commands.

Check the plan against:

- {{SPEC_DIR}}/spec.md;
- .specify/memory/constitution.md;
- docs/architecture/.

Focus on:

- whether the technical approach satisfies the spec;
- whether the Constitution Check is credible;
- whether the plan introduces unnecessary abstractions;
- whether domain boundaries are minimal and clear;
- whether provider-specific and domain-specific logic remain isolated;
- whether validation is provider-free;
- whether migration and documentation impacts are covered;
- whether artifact contracts and metric provenance are preserved.

Return:

- plan readiness;
- required changes before tasks;
- risks;
- overengineering concerns;
- missing tests or contracts.
```
