# Common constraints

Paste these constraints at the start of Spec Kit, Claude, or Codex prompts unless explicitly overridden.

```text
Do not create or switch branches.
Do not implement code unless explicitly requested.
Do not run provider-backed commands.
Do not run the full benchmark.
Prefer provider-free validation, fixtures, mocks, and focused tests.
Do not perform opportunistic refactors.
Keep changes scoped to the active specification.
Prefer the simplest design that preserves research validity, reproducibility, traceability,
artifact contracts, metric provenance, phase separation, and migration expectations.
Avoid speculative plugin frameworks, excessive metadata, broad rewrites, or future-proofing
not justified by current specs and current domains.
```
