# Lattes migration spec

```text
/speckit.specify

SPECIFY_FEATURE_DIRECTORY=specs/005-lattes-dataset-migration

Create a spec for migrating the Lattes dataset integration to the domain-neutral artifact model.

Scope:
- raw HTML as source artifact;
- cleaned/minified HTML as context artifact;
- parsed JSON as normalized/context artifact;
- blocks JSON as evidence artifact;
- questions as tasks;
- question-instance mappings as task-instance mappings;
- compatibility with existing Lattes experiments.

Out of scope:
- software repository domain;
- new benchmark strategies;
- provider-backed execution.

Do not create or switch branches.
Do not implement code.
Do not run provider-backed commands.
```
