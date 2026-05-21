# C4 — Component Diagram

## Diagram

```mermaid
flowchart TB
    subgraph Planning["Planning components"]
        ExperimentLoader["Experiment Loader"]
        DatasetResolver["Dataset Resolver"]
        DatasetCache["Dataset cache"]
        AdapterRegistry["Adapter Registry<br/>ctxbench.adapters.registry"]
        DatasetContracts["Generic dataset contracts<br/>ctxbench.dataset"]
        LattesAdapter["Lattes adapter<br/>ctxbench.adapters.lattes"]
        TrialPlanner["Trial Planner"]
        ManifestWriter["Manifest Writer"]
        TrialWriter["Trial Writer"]
    end

    subgraph Execution["Execution components"]
        TrialReader["Trial Reader"]
        ExecutionEngine["Execution Engine"]
        StrategyFactory["Strategy Factory"]
        ModelAdapter["Model Adapter"]
        ToolRuntime["Function / MCP Runtime"]
        ResponseWriter["Response Writer"]
        ExecutionTraceWriter["Execution Trace Writer"]
    end

    subgraph Evaluation["Evaluation components"]
        ResponseReader["Response Reader"]
        EvalJobBuilder["Evaluation Job Builder"]
        JudgeAdapter["Judge Model Adapter"]
        VoteWriter["Judge Vote Writer"]
        EvalAggregator["Evaluation Aggregator"]
        EvalWriter["Evaluation Writer"]
        EvalTraceWriter["Evaluation Trace Writer"]
    end

    subgraph Export["Export components"]
        ArtifactReader["Artifact Reader"]
        RowBuilder["Result Row Builder"]
        CsvWriter["CSV Writer"]
    end

    ExperimentLoader --> DatasetResolver
    DatasetResolver --> DatasetCache
    DatasetResolver --> AdapterRegistry
    AdapterRegistry --> LattesAdapter
    LattesAdapter --> DatasetContracts
    DatasetContracts --> TrialPlanner
    TrialPlanner --> ManifestWriter
    TrialPlanner --> TrialWriter

    TrialReader --> ExecutionEngine
    DatasetContracts --> ExecutionEngine
    ExecutionEngine --> StrategyFactory
    StrategyFactory --> ModelAdapter
    StrategyFactory --> ToolRuntime
    ExecutionEngine --> ResponseWriter
    ExecutionEngine --> ExecutionTraceWriter

    ResponseReader --> EvalJobBuilder
    DatasetContracts --> EvalJobBuilder
    EvalJobBuilder --> JudgeAdapter
    JudgeAdapter --> VoteWriter
    VoteWriter --> EvalAggregator
    EvalAggregator --> EvalWriter
    JudgeAdapter --> EvalTraceWriter

    ArtifactReader --> RowBuilder
    RowBuilder --> CsvWriter
```

## Component notes

The components are implemented as Python modules. During migration, some implementation details may
still live behind compatibility adapters, but the target ownership is:

```text
ctxbench.cli
ctxbench.commands
ctxbench.benchmark
ctxbench.dataset
ctxbench.adapters.registry
ctxbench.adapters.lattes
ctxbench.ai
```

## Dataset and adapter components

`ctxbench.dataset` owns generic contracts, payloads, errors, capability reports, and adapter
registry primitives. It does not import concrete adapters.

`ctxbench.adapters.registry` owns first-party wiring. It registers dataset identities, such as
`ctxbench/lattes`, to factories that create concrete adapters from resolved dataset provenance.

`ctxbench.adapters.lattes` is a concrete first-party adapter. It may depend on `ctxbench.dataset`
contracts, but the benchmark core must not import it directly.

The intended dependency direction is:

```text
ctxbench.benchmark / ctxbench.commands -> ctxbench.dataset <- ctxbench.adapters.lattes
composition root -> ctxbench.adapters.registry
```
