# Review spec roadmap

Use this after drafting multiple specs or a roadmap.

```text
Review the spec roadmap in {{ROADMAP_FILE}} and the specs listed there.

Do not edit files.
Do not implement code.
Do not run provider-backed commands.

Check:

- Are specs ordered correctly?
- Are dependencies explicit?
- Is any spec too broad?
- Is any spec too small to justify a separate implementation branch?
- Are any specs blocking each other unnecessarily?
- Are any future specs too detailed too early?
- Are there missing specs for artifact contracts, migration, metrics, domain boundaries, or documentation?
- Does the roadmap avoid a single huge implementation branch?

Return:

- recommended sequence;
- specs that should be merged/split;
- specs that are ready for planning;
- specs that should remain lightweight;
- implementation branch recommendations.
```
