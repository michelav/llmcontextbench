# Set active feature

Use this before `/speckit.plan` or `/speckit.tasks` when multiple specs exist in the same branch.

```bash
printf '{ "feature_directory": "{{SPEC_DIR}}" }\n' > .specify/feature.json
cat .specify/feature.json
```

Expected output:

```json
{ "feature_directory": "{{SPEC_DIR}}" }
```

Optional sanity check:

```bash
test -f {{SPEC_DIR}}/spec.md && echo "Spec found"
```
