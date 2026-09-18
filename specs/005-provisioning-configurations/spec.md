# Explicit provisioning configurations

Status: accepted for implementation. Level 3.

## Goal and scope
A named provisioning configuration is the experimental treatment: a required strategy and representation. This changes experiment schemas, planning, identity, lifecycle artifacts, AI interfaces, selectors, metrics, analysis and documentation. It does not change prompts, provider behavior, judging, token provenance or execution/evaluation cost separation.

## Requirements
1. Experiments define top-level configurations keyed by lowercase identifiers, each with exactly strategy and representation. factors.configuration is nonempty, unique and references defined entries. Reject legacy factors.strategy/format, unknown strategies and unexpected definition fields.
2. Expand instances × tasks × models × selected configurations × repeats. Tool strategies support only json; inline availability is checked by the dataset adapter. Never silently substitute a representation.
3. Persist configurationId, strategy and representation in trials, responses and shared metadata; evaluation inherits metadata. Validate duplicates. Judge votes link by trialId.
4. Snapshot selected definitions in the manifest. Execution uses planned trials, never a changed experiment definition.
5. Identity uses deterministic structured encoding with an identity version, existing identity dimensions, configuration ID and definition. Renames and definition changes change identity; dictionary order does not.
6. Require provisioning artifact contract version at lifecycle entry points. Reject legacy artifacts with instructions to use the previous benchmark version or plan into a fresh directory. Never mutate historical artifacts.
7. Reject conflicting definitions of an ID across analysis inputs. Distinct IDs remain distinct even with equal definitions.
8. Select by configuration, strategy and representation, including exclusions. Export persisted identity; metrics default to dataset_id,configurationId and version their changed schemas. Representation replaces the format robustness axis.
9. Notebook reads trials/responses/evals/judge_votes using trialId/taskId and persisted configurations; clear saved outputs, preserve statistical calculations and verify small fixtures. Strategy pooling must be disclosed.
10. Defer operation profiles: no registry or placeholder fields. A future typed operationProfile must include resolved content in identity.

## Acceptance
Three configurations yield exactly three treatments per remaining factor combination. Function/json retains behavior; function/html fails. Editing an experiment after planning cannot change execution. Every reported treatment traces to its definition. Costs, votes and unavailable values retain their meanings.

## Compatibility
Clean break, no migration or inferred configurations. Historical files require the preceding benchmark version.
