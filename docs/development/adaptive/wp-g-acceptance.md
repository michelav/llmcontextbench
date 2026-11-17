# WP-G acceptance report: workload builder and experiments in code

**Status:** implementation complete; acceptance review pending.

WP-G adds deterministic dataset-backed workload generation, strict request-feature filtering and
label projection, adaptive definition section builders, `load_dataset`, `Scenario`, and a provider-free
code-built example. Both generated and explicit workloads are expanded to the same frozen request
records. Adaptive definition files and code-built `AdaptiveExperiment` objects normalize to the same
resolved definition and plan.

Workload sampling uses SHA-256 based ordering and draw selection keyed by the seed, segment index,
and sorted pool. This keeps generation stable across processes and Python runtimes. Without-replacement
sampling resets for each segment; each segment fails if its filtered pool is smaller than its size.

## Acceptance checks

- Equal generator specifications produce identical expanded requests and pool digests in separate
  processes.
- Declared categorical filtering and feature-to-label projection work; unknown features and
  undersized without-replacement pools fail clearly.
- Code-built and file-defined experiments produce byte-identical `adaptive-plan.json`,
  `resolved.json`, and execution fingerprints.
- Section builders round-trip normalized mappings; the scenario helper returns workload and
  disturbance sections.
- The code-built example plans successfully with the fake dataset and mock provider.
- Focused tests: `39 passed` across workload builder, adaptive workflow, and API workflow tests.
- Full provider-free suite: `563 passed` (`pytest -q`). No real-provider execution or evaluation was
  run.

## Design item requiring acceptance review

Section 11 asks a generated workload and its explicit expansion to produce byte-identical plans,
while section 6.11 also requires the plan to retain the generator specification and pool digest.
Those requirements produce different `workloadSource` values for a generator definition and a
plain explicit list. This implementation verifies byte-identical frozen request records; complete
plan bytes differ in `workloadSource`. The review should decide whether explicit expansions carry
generator provenance or whether this gate compares the frozen requests.
