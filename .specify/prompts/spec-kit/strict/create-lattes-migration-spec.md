# Create Lattes dataset migration spec

Use this with `/speckit.specify`.

```text
/speckit.specify

Do not create or switch branches.
Do not implement code.
Do not run provider-backed commands.

SPECIFY_FEATURE_DIRECTORY=specs/005-lattes-dataset-migration

Create a specification named "lattes-dataset-migration".

The goal is to migrate the existing Lattes dataset integration to the domain-neutral artifact model.

The migration must preserve current experiment behavior while changing internal naming and
metadata toward the target vocabulary.

The spec must map current Lattes files to semantic artifact roles:

- raw HTML as source artifact;
- cleaned/minified HTML as context artifact;
- parsed JSON as normalized/context artifact;
- blocks JSON as evidence artifact;
- questions as tasks;
- question-instance mappings as task-instance mappings.

The spec must preserve compatibility with existing Lattes experiments where practical.

The spec must not add the software repository domain.
Do not run provider-backed commands.
```
