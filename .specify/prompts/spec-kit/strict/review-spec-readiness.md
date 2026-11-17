# Review spec readiness

Use this before `/speckit.plan`.

```text
Review {{SPEC_DIR}}/spec.md for readiness to plan.

Do not edit files.
Do not implement code.
Do not run provider-backed commands.

Check:

- Is the scope clear?
- Are non-goals explicit?
- Are user stories independently testable?
- Are requirements testable and unambiguous?
- Are dependencies on other specs stated?
- Are artifact, metric, domain, strategy, and documentation impacts identified?
- Does the spec avoid implementation details?
- Does it comply with the constitution?
- Does it avoid speculative abstractions?
- Does it identify compatibility or migration expectations when needed?

Return:

- Ready / Not ready;
- blocking issues;
- suggested edits;
- questions that must be resolved before planning.
```
