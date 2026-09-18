# Implementation plan

Accepted user design; no additional approval needed. Reuse typed configuration fields through inheritance and existing lifecycle readers; no new registry.

| Slice | Goal / files | Checks | Dependencies / risk | Commit |
|---|---|---|---|---|
| 1 | Contract, benchmark/models.py, runspec_generator.py, util/artifacts.py, commands/plan.py, experiment fixtures | references, rejection, expansion, identity | first; treatment counts | feat: define explicit provisioning configurations |
| 2 | Executor, AI request, dataset helpers, metadata, lifecycle guards | mocked lifecycle, snapshot consistency, legacy rejection | 1; metadata mismatch | refactor: propagate provisioning identity through lifecycle |
| 3 | CLI, selectors, export/status, metrics | filters, columns, defaults, conflicts, artifact-only operation | 2; pooling | feat: expose provisioning configurations in reports |
| 4 | Notebook, examples, documentation, migrated tests | small fixture notebook, provider-free suite | 3; stale schemas | docs: align analysis with provisioning configurations |

Invariants: unchanged strategy implementation and provider requests, prompts, evaluation rules, metric provenance, vote availability and separated costs. Physical dataset filenames and representation values stay unchanged. Serialization/provider response format terminology stays intact. No new dependencies, lockfile changes or live provider calls.
