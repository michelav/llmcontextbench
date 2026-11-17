# Simplify spec or design

Use this when a spec, plan, or design seems overengineered.

```text
Simplify {{TARGET_FILE}}.

Do not remove research-critical requirements.
Do not implement code.
Do not run provider-backed commands.

Review the document for overengineering.

Prefer the simplest model that preserves:

- research validity;
- reproducibility;
- traceability;
- artifact contracts;
- metric provenance;
- phase separation;
- migration expectations.

Remove or mark as future work any concepts not required by current accepted specs and current known domains.

Avoid:

- speculative plugin frameworks;
- complex registries;
- excessive metadata fields;
- broad rewrites;
- unnecessary layers;
- future-proofing not justified by the active spec.

Return:

- what was simplified;
- what was preserved and why;
- any risks introduced by simplification;
- follow-up changes needed in spec/plan/tasks.
```
