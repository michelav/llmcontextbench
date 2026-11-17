# Update spec

Use this when intent, scope, public contracts, compatibility, or semantics changed.

```text
Update {{SPEC_DIR}}/spec.md.

Do not update plan.md or tasks.md yet.
Do not implement code.
Do not create or switch branches.
Do not run provider-backed commands.

Incorporate this decision:

{{DECISION}}

Update the spec to state, when relevant:

- what changed;
- why the change is needed;
- whether it affects scope;
- whether it affects public contracts;
- whether it affects artifact semantics;
- whether it affects metric semantics or provenance;
- whether it affects compatibility or migration;
- whether it affects documentation;
- whether any prior requirement or non-goal must change.

Preserve existing scope unless the decision explicitly changes it.
Do not add implementation details unless they are necessary to define a public contract.

After editing, report:

- sections changed;
- contracts or assumptions changed;
- whether plan.md must be updated next;
- whether tasks.md must be regenerated.
```
