# Review implementation slices

```text
Review implementation slices in {{SPEC_DIR}}/plan.md or {{SPEC_DIR}}/tasks.md.

Do not edit files.
Do not implement code.
Do not run provider-backed commands.

Check:
- Is each slice cohesive?
- Is each slice small enough to review?
- Does each slice end in a green checkpoint?
- Are tests/checks focused and provider-free?
- Are unrelated concerns mixed?
- Are future specs being pulled in?
- Are worklog/usage updates included only where useful?

Return:
- slices that are ready;
- slices that should be split;
- missing validation;
- overengineering risks.
```
