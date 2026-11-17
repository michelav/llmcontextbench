# Dataset artifact model spec

```text
/speckit.specify

SPECIFY_FEATURE_DIRECTORY=specs/004-dataset-artifact-model

Create a spec for a domain-neutral dataset artifact model.

Goal:
Represent dataset artifacts by semantic role and representation, not by Lattes-specific filenames.

Scope:
- source artifacts;
- context artifacts;
- evidence artifacts;
- normalized/derived artifacts;
- metadata artifacts;
- how strategies select context artifacts;
- how evaluation selects evidence artifacts;
- compatibility with Lattes and a future software repository domain.

Out of scope:
- implementing the software repository domain;
- large artifact taxonomy;
- speculative plugin framework.

Do not create or switch branches.
Do not implement code.
Do not run provider-backed commands.
```
