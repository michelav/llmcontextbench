# C4 — Deployment Diagram

## Purpose

This diagram documents the physical/runtime topology.

This is the best C4 view for showing where the LLMContextBench Python process runs, where artifacts are stored, where LLM providers are called, and how local and remote MCP differ.

## Deployment: inline and local function strategies

```mermaid
flowchart TB
    subgraph Node1["Researcher workstation or CI runner"]
        CLI["LLMContextBench Python process<br/>llmctxbench"]
        FS["Local filesystem<br/>dataset, experiments, outputs"]
        FUNC["Local Python functions<br/>local_function strategy"]
    end

    LLM["External LLM provider API"]

    CLI <--> FS
    CLI <--> FUNC
    CLI <--> LLM
```

## Deployment: local MCP strategy

```mermaid
flowchart TB
    subgraph Node1["Researcher workstation or CI runner"]
        CLI["LLMContextBench Python process<br/>ctxbench"]
        FS["Local filesystem<br/>dataset, experiments, outputs"]
        subgraph MCPLOCAL["Local MCP runtime"]
            MCPC["MCP client"]
            MCPS["Local MCP server<br/>FastMCP/tools"]
        end
    end

    LLM["External LLM provider API"]

    CLI <--> FS
    CLI <--> LLM
    CLI <--> MCPC
    MCPC <--> MCPS
    MCPS <--> FS
```

## Deployment: remote MCP strategy

```mermaid
flowchart TB
    subgraph Node1["Researcher workstation or CI runner"]
        CLI["LLMContextBench Python process<br/>ctxbench"]
        FS["Local filesystem<br/>experiment outputs"]
    end

    subgraph Provider["LLM Provider Environment"]
        LLM["LLM model / provider tool orchestration"]
    end

    subgraph Remote["Remote context environment"]
        MCPS["Remote MCP server"]
        STORE["Context store<br/>dataset artifacts, database, object storage"]
    end

    CLI <--> FS
    CLI <--> LLM
    LLM <--> MCPS
    MCPS <--> STORE
```

## Deployment notes

| Strategy | Runtime topology |
|---|---|
| `inline` | LLMContextBench reads local context and sends it to provider in the model input. |
| `local_function` | LLMContextBench executes local Python functions that read local dataset artifacts. |
| `local_mcp` | LLMContextBench uses a local MCP client/server boundary, usually with local files. |
| `remote_mcp` | Provider/model interacts with a remote MCP server that reads a remote or service-side context store. |

## Why deployment matters for MCP

The remote MCP strategy changes the physical architecture:

```text
- context serving moves out of the LLMContextBench process
- a network boundary is introduced
- part of the tool loop may become provider-managed
- observability can decrease
- latency and availability become deployment concerns
```

Therefore, remote MCP should be documented primarily with a C4 deployment diagram and complemented by a dynamic diagram.
