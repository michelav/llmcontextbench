# Provisioning contract v1

Manifest: provisioningArtifactVersion = 1, configurations = selected ID-to-definition map.
Definition: exactly {strategy: string, representation: nonempty string}; strategy is inline, local_function, local_mcp or remote_mcp. Non-inline requires json. IDs match ^[a-z][a-z0-9_.-]*$.
Trial identity: canonical JSON with identityVersion = 2, experimentId, taskId, instanceId, provider, modelName, configurationId, configuration (resolved definition), repeatIndex, sorted keys and compact separators; SHA-256 short IDs retain existing collision handling.
Canonical: trials.jsonl, responses.jsonl, evals.jsonl, judge_votes.jsonl and traces. Trials and responses carry configurationId, strategy, representation at root and in metadata, with equality enforced. Evaluations carry shared metadata; judge votes retain trialId links. Manifest definitions and artifact definitions must agree.
Derived: CSV exports and metrics. Default grouping dataset_id,configurationId; retain strategy and representation columns for explicit aggregation. Combining a configuration ID with unequal definitions is an error.
Historical artifacts are read only with the previous release. Re-plan experiments with explicit configurations in a new directory.
