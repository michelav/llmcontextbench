# C4 — Dynamic Diagrams

## Purpose

Dynamic diagrams document runtime behavior for the dataset-distribution flow added by Spec 003.

## Successful remote dataset fetch

```mermaid
sequenceDiagram
    participant U as Researcher
    participant C as llmctxbench dataset fetch
    participant R as Remote dataset repository
    participant V as SHA-256 source
    participant X as Safe extractor
    participant K as Local dataset cache

    U->>C: dataset id + origin + version + checksum input
    C->>V: read trusted checksum
    V-->>C: expected SHA-256
    C->>R: download archive asset
    R-->>C: tar.gz bytes
    C->>C: verify SHA-256 before extraction
    C->>X: safe extract tar.gz
    X-->>C: extracted package root
    C->>C: discover exactly one manifest
    C->>K: store materialization + provenance
    K-->>U: local dataset available
```

## Inspect reports a non-conformant package

```mermaid
sequenceDiagram
    participant U as Researcher
    participant I as llmctxbench dataset inspect
    participant R as DatasetResolver
    participant P as DatasetPackage

    U->>I: inspect dataset-ref
    I->>R: resolve local dataset
    R-->>I: package
    I->>P: validate capabilities
    P-->>I: capability report with missing mandatory items
    I-->>U: conformant = false + missing_mandatory
```

## Plan rejected on missing dataset

```mermaid
sequenceDiagram
    participant U as Researcher
    participant P as llmctxbench plan
    participant R as DatasetResolver
    participant K as Local dataset cache

    U->>P: experiment.json with dataset id@version
    P->>R: resolve dataset reference
    R->>K: lookup dataset id + version
    K-->>R: no match
    R-->>P: DatasetNotFoundError
    P-->>U: fail with fetch remediation
```

## Plan rejected on ambiguous dataset

```mermaid
sequenceDiagram
    participant U as Researcher
    participant P as llmctxbench plan
    participant R as DatasetResolver
    participant K as Local dataset cache

    U->>P: experiment.json with dataset id@version
    P->>R: resolve dataset reference
    R->>K: lookup conflicting materializations
    K-->>R: more than one conflicting match
    R-->>P: AmbiguousDatasetError
    P-->>U: fail without choosing one silently
```
