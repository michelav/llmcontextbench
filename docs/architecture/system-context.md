# C4 — System Context

> Transition note: this page describes the existing implementation. The accepted
> [v1 target architecture and contracts](v1-contracts.md) describe the refactor;
> [slice tracking](../../specs/009-llmctxbench-v1/tasks.md) identifies what is implemented.

## Diagram

```mermaid
flowchart LR
    R["Researcher / Experiment Designer"]
    A["Analyst / Reviewer"]
    C["LLMContextBench<br/>Python CLI benchmark runner"]
    D["Dataset package<br/>instances, tasks, context artifacts"]
    L["LLM providers<br/>OpenAI, Google, Anthropic, etc."]
    M["Remote MCP server<br/>optional"]
    N["Analysis tools<br/>notebooks, pandas, DuckDB, spreadsheets"]

    R -->|"defines experiments and runs workflow"| C
    D -->|"provides benchmark inputs"| C
    C -->|"prompts, messages, tool definitions"| L
    C -->|"optional remote context access"| M
    C -->|"JSONL, CSV, traces"| N
    A -->|"inspects results and traces"| N
```

## Explanation

LLMContextBench is a local/CI-executed research tool that orchestrates benchmark experiments over dataset packages and LLM providers.

It can optionally interact with remote MCP servers when evaluating protocol-based context provisioning.
