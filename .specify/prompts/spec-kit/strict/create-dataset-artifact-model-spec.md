# Create dataset artifact model spec

Use this with `/speckit.specify`.

```text
/speckit.specify

Do not create or switch branches.
Do not implement code.
Do not run provider-backed commands.

SPECIFY_FEATURE_DIRECTORY=specs/004-dataset-artifact-model

Create a specification named "dataset-artifact-model".

The goal is to define a domain-neutral dataset artifact model.

The model must avoid assuming Lattes-specific files such as raw HTML, cleaned HTML, parsed JSON,
or blocks JSON.

A dataset artifact must be described by semantic role and representation, not only by filename.

The spec must distinguish at least:

- source artifacts;
- context artifacts;
- evidence artifacts;
- normalized or derived artifacts;
- metadata artifacts.

The spec must define how a strategy selects context artifacts and how evaluation selects
evidence artifacts.

The spec must support both the current Lattes domain and a future software repository domain.

Examples:

- A Lattes raw HTML file may be a source artifact.
- A cleaned Lattes HTML file may be a context artifact.
- A parsed Lattes JSON file may be a normalized/context artifact.
- A Lattes blocks file may be an evidence artifact.
- A software repository snapshot may be a source artifact.
- A code index may be a context artifact.
- Ground-truth annotations may be evidence artifacts.

The spec must not implement the software repository domain yet.
It may update the Lattes dataset adapter to use the new semantic artifact model.
Do not run provider-backed commands.
```
