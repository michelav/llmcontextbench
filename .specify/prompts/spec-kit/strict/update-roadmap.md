# Update spec roadmap

Use this when the sequence or status of specs changes.

```text
Update specs/README.md or docs/roadmap/refactor-sequence.md.

Do not update individual specs.
Do not implement code.
Do not run provider-backed commands.

Reflect the current planned sequence:

{{ROADMAP_ITEMS}}

For each item, include:

- goal;
- depends on;
- enables;
- current status: draft / planning-ready / planned / in implementation / done;
- implementation branch, if known;
- notes about scope or deferred decisions.

Keep it short and useful for humans and agents.
```
