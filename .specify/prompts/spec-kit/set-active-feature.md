# Set active feature

Use when multiple specs exist in the same branch.

```bash
printf '{ "feature_directory": "{{SPEC_DIR}}" }\n' > .specify/feature.json
cat .specify/feature.json
```

Then use `/speckit.plan` or `/speckit.tasks`.
