# Compare full spec and lite spec

Use this prompt after converting a spec to lite format.

```text
Compare the current lightweight spec with the previous/full version of the spec.

Spec path:
{{SPEC_DIR}}/spec.md

If a previous version is available through git, compare against it.
If not, compare against the provided diff.

Do not edit files.
Do not implement code.
Do not run provider-backed commands.

Check:
- Did any accepted requirement disappear?
- Did any compatibility or migration decision disappear?
- Did any public contract become ambiguous?
- Did any acceptance scenario lose testability?
- Did any out-of-scope item disappear?
- Did the conversion remove only boilerplate/repetition/implementation detail?
- Does the lite spec remain sufficient for planning?

Return:
- safe / unsafe conversion;
- missing or weakened items;
- recommended fixes;
- whether the spec is ready for planning.
```
