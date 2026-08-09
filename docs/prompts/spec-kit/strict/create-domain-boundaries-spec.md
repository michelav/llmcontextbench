# Create domain architecture boundaries spec

Use this with `/speckit.specify`.

```text
/speckit.specify

Do not create or switch branches.
Do not implement code.
Do not run provider-backed commands.

SPECIFY_FEATURE_DIRECTORY=specs/003-domain-architecture-boundaries

Create a specification named "domain-architecture-boundaries".

The goal is to make LLMContextBench domain-neutral before adding a new software repository domain.

The current Lattes dataset must become one domain implementation, not an assumption of the benchmark core.

The spec must define the responsibilities and boundaries of:

- benchmark core;
- dataset package;
- domain adapter;
- instance reader;
- task loader;
- context artifact provider;
- evidence artifact provider;
- tool provider;
- evaluation evidence provider.

The spec must ensure that generic benchmark code does not depend on Lattes-specific concepts
such as curriculum, HTML curriculum, parsed curriculum, or Lattes blocks.

The spec must not implement the software repository domain yet. It should only define and
implement the minimum architecture needed to support more than one domain.

The design must avoid speculative plugin frameworks unless justified by current needs.
Do not run provider-backed commands.
```
