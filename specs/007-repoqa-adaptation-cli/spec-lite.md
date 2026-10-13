# RepoQA adaptation CLI (Level 2)

Expose prepare, calibrate, freeze, episode and analyze under the experimental
`llmctxbench adaptation repoqa` group. Preserve script arguments/defaults, policy
order, execution semantics, recovery rules and JSON output. The script remains a
compatibility wrapper; its internal Python functions are not an API.

Canonical and derived artifacts retain their existing schemas and layout. No
artifact migration or regeneration is required. Completed studies remain readable;
pre-migration studies must use their original source identity for continuation.
Missing Git provenance or scorer helpers must fail actionably. Help and unrelated
commands must not initialize the scorer. No providers, dependency changes, dataset
regeneration, lean-surface work, new policies or batch/status features are in scope.

Acceptance: shared implementation, focused regression tests plus mocked workflow
parity, coherent maintained documentation, intentional historical references.
