# Adaptive plan (`adaptive-plan.json`, version 4)

The frozen adaptive plan is the authority for an adaptive run. `plan` writes it from an adaptive
definition (`workflowKind: "adaptive"`, `schemaVersion: 4`); `execute`, `status`, `eval`,
`export` and `metrics` read it and never re-read the definition. The definition is documented
in [the adaptive definition reference](../../guide/reference/definition-adaptive.md); its
machine-readable form is `ctxbench.adaptive.definition.adaptive_definition_schema()`.

Writer and reader: `ctxbench/adaptive/artifacts.py` (`adaptive_plan_payload`,
`adaptive_plan_from_payload`). Model: `ctxbench/adaptive/plan.py` (`AdaptivePlan`,
`CandidateSpec`, `PlannedRequest`).

## Shape

Every object below has exactly these keys; a plan with a missing or extra key is rejected.

```json
{
  "adaptivePlanVersion": 4,
  "workflowId": "<experiment-id>",
  "seed": 1,
  "labels": {},
  "candidates": [
    {"candidateId": "A", "labels": {}, "modelId": "m1", "provider": "mock", "modelName": "mock",
     "modelParams": {}, "configurationId": "c1",
     "configuration": {"strategy": "inline", "representation": "…", "surface": "s1"},
     "surfaceSpec": {}, "executionOptions": {}}
  ],
  "requests": [
    {"requestId": "r-0001", "sequenceIndex": 1, "taskId": "…", "instanceId": "…",
     "taskStatement": "…", "taskTemplate": "…", "parameters": {}, "taskTags": [],
     "validationType": null, "validationConfig": {}, "contextBlocks": [], "labels": {}}
  ],
  "workloadSource": {"kind": "explicit", "spec": {"requests": []}},
  "policy": {"ref": "window_threshold", "id": "window_threshold", "version": "1",
             "params": {}, "sourceDigest": "<sha256>", "sources": []},
  "window": {"requests": 10, "mode": "sliding"},
  "signals": [],
  "acceptance": {"minimumResponseLength": 0},
  "goals": [],
  "disturbances": [],
  "evaluation": {"enabled": false, "judges": []},
  "trace": {},
  "allowMixedModels": false,
  "provenance": {
    "dataset": {"digest": "<sha256>"},
    "implementation": {"digest": "<sha256>", "dependencies": {"<package>": "<version>"}}
  }
}
```

## Fields

| Field | Content |
|---|---|
| `workflowId` | The definition `id`. Also `experimentId` and `workflowId` in the manifest. |
| `seed` | Integer run seed; the source of `state.rng()` for policies. |
| `labels` | Opaque run labels, copied to the manifest and to metric rows. |
| `candidates` | The catalogue, in declared order. Each candidate is one model plus one provisioning configuration, resolved once at `plan`. The catalogue is the same for every request. |
| `requests` | The workload, in execution order. `sequenceIndex` is contiguous from 1. Task statements are rendered at `plan`. `labels` hold the request labels, including feature values copied by a generator's `labelFeatures`. |
| `workloadSource` | Where the requests came from: `{"kind": "explicit", "spec": {"requests": [...]}}` or `{"kind": "generator", "spec": <generator>, "poolDigest": <sha256>}`. |
| `policy` | `ref` as written in the definition; `id` and `version` from the policy class; validated `params`; `sourceDigest`, a digest over the source file of the policy class (built-in or external) and the files in `sources`; `sources` recorded relative to the policy module's directory. |
| `window` | The experiment's default window. A definition window `{"all": true}` is frozen as `{"requests": <number of requests>}`. |
| `signals` | Declared quality signals, each resolved to its assessor: `id`, `assessor`, `metricId`, `assessorVersion`, `sensorClass`, `valueProvenance`, `valueScale`, `usesReferenceData`, `declaredCost`, and `sourceDigest`/`sources` for an assessor with a locatable source. |
| `acceptance` | `minimumResponseLength` (default `0`). |
| `goals`, `disturbances` | The normalised definition sections. |
| `evaluation`, `trace` | Offline evaluation and trace settings, copied to the manifest. |
| `allowMixedModels` | `true` only when the definition opts in to candidates with different models. |
| `provenance.dataset.digest` | Digest of the materialised dataset tree, or the dataset's declared `contentHash` when it has no materialised path. |
| `provenance.implementation` | Digest of the installed `ctxbench` implementation and the versions of the dependencies it covers. Recorded, not enforced (see below). |

The plan size is `O(requests + candidates)`. It contains no per-request candidate lists and no
pre-built execution requests; `ctxbench/adaptive/invocation.py` builds the execution request for
the selected candidate at decision time.

## The plan is the fingerprint

`executionFingerprint` in the manifest is the SHA-256 of the `adaptive-plan.json` file. The
plan holds everything the run depends on besides its own content: plug-in source digests and
`provenance`. `resolved.json` is written for readers and is not hashed.

`execute` refuses to run when:

- `adaptive-plan.json` no longer hashes to `executionFingerprint`;
- the dataset digest differs from `provenance.dataset.digest`;
- the policy's source digest differs from the plan (this covers built-in policies too: a
  changed built-in policy module is refused, unlike other implementation changes);
- an online assessor's source digest, source list or declared capability differs from the plan.

The implementation digest is not checked. Each attempt records the digest of the implementation
that executed it (`implementationDigest`, see [records](records.md)); `status` and `metrics`
report a run whose attempts span more than one implementation.

## Version policy

Only `adaptivePlanVersion: 4` is read. Any other version fails with
"create a fresh adaptive plan"; there is no migration and no compatibility reader.
