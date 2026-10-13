# Lean RepoQA surface and strategy comparison

Status: lean operations implemented. The V3 study protocol supersedes the adaptive-candidate restriction below; see `docs/studies.md`.

## Summary

Add an opt-in `repoqa-lean` operation surface, available through both existing strategies: `local_function` and `local_mcp`.

Keep the primary adaptation study focused on **inline versus local MCP with the lean surface**. Use local functions in a separate supporting comparison to distinguish operation-payload costs from MCP integration overhead.

Preserve the existing surface, dataset artifacts, and completed study. Study CLI integration is documented in `docs/studies.md`.

## Lean operation contract

Retain existing operation arguments, workspace boundaries, stable symbol IDs, and path/kind filtering.

| Operation | Successful result |
|---|---|
| `list_files_lean` | Array of visible file-path strings |
| `list_symbols_lean` | Flat array of `{symbol_id, name, kind, documentation?}` |
| `get_symbol_lean` | `{"code": "..."}` |
| `read_file_lean` | `{"content": "..."}` |

For symbol discovery, use the qualified name when available and retain full available documentation. Omit empty documentation.

- Exclude signatures, code bodies, parent records, line numbers, repeated paths, repository metadata, and empty child arrays from listings.
- Flatten nested symbols in deterministic order, returning each symbol ID once.
- Apply kind filters independently to each symbol; matching descendants remain discoverable even when their parent does not match.
- Preserve `kind="function"` matching both functions and methods.
- Return all matches without pagination, ranking, or truncation.
- Retrieve complete available code once, without separate copies of child implementations.
- Use explicit tool errors for unknown identifiers or unavailable code.
- Keep evaluation information inaccessible to operations.

Register these names under `repoqa-lean`. Keep `repoqa-default` and its operations unchanged. Calls without an explicit operation allow-list retain the original four-tool default.

## Implementation slices

Treat this as a Level 3 research-facing change: establish the specification and response contract before implementation, then implement one tested slice at a time.

| Slice | Work and likely location | Focused validation | Dependency / suggested commit |
|---|---|---|---|
| 1. Lean projections | Add provider methods in the RepoQA adapter, reusing existing lookup and visibility logic | Nested symbols, filtering, distinct IDs, documentation, missing code, visibility boundaries; existing verbose results unchanged | Contract approved; `feat(repoqa): add lean operation projections` |
| 2. Tool exposure | Extend RepoQA tool catalog, handlers, surface validation, and MCP registration | Allow-list enforcement, unchanged defaults, equivalent local-function/MCP results, normalized error behavior | Slice 1; `feat(repoqa): expose lean operation surface` |
| 3. Experiment configuration | Add separate benchmark and adaptation examples plus documentation | Planning, treatment identity, persisted operation lists, initial-prompt budgeting, mocked adaptation execution | Slice 2; `docs(repoqa): add lean surface study configurations` |
| 4. Payload audit | Add a provider-free comparison utility and regression fixtures | Serialized schema/result size, symbol coverage, documentation preservation, code equality across four languages | Slices 1–3; `test(repoqa): validate lean surface payload reductions` |

Use concise tool descriptions shared consistently across transports. Preserve `representation: "json"`; the lean surface changes operation content rather than selecting a different serialization format.

## Study design

**Primary adaptation study**

Compare the existing four policies:

- Always inline.
- Always local MCP using `repoqa-lean`.
- Frozen router.
- Adaptive router.

Keep stationary and degradation–recovery scenarios. Preserve the runner's required candidate IDs and `inline/code` versus `local_mcp/json` pairing; select the new MCP surface through configuration.

Create a fresh study directory and perform preparation, calibration, and freezing again. Before committing to the full study, check whether lean MCP creates a useful operating trade-off with inline. Smaller responses alone do not establish adaptive benefit.

**Supporting strategy comparison**

Use the standard benchmark workflow for this matrix:

| Strategy | Existing surface | Lean surface |
|---|---|---|
| `local_function` | Baseline | Lean comparison |
| `local_mcp` | Baseline | Lean comparison |

Hold inputs, model, execution limits, and corresponding operation capabilities constant. Verify model-visible schemas and normalized responses before attributing differences to transport.

Measure quality, total execution tokens, latency, tool calls, and execution failures. Report schema/result payload sizes separately from provider-reported usage.

For the V3 study protocol, local functions are included in the adaptive candidate set. The historical two-candidate protocol retains its own restriction.

## Acceptance, compatibility, and limits

Implementation is complete when:

- Existing verbose-operation tests remain green.
- Lean listings preserve matching symbols and available documentation without signatures or code bodies.
- Lean retrieval returns the same visible code/file content as existing operations.
- Both execution strategies support the lean surface, with no duplicated transport payload.
- Representative metadata-heavy results have lower serialized payload sizes.
- Saved experiment artifacts clearly distinguish the selected surfaces.

Keep existing datasets and `runs/repoqa-adaptive-001` unchanged. Defer the dataset-builder signature-extraction repair: excluding signatures allows the surface comparison to use identical dataset artifacts.

Do not change scoring, provider serialization, continuation handling, execution step limits, or generic artifact schemas. The main risks are reduced discoverability and additional retrieval calls; the paired comparison must measure both.

Character/byte reductions are structural measurements, not demonstrated token or monetary savings. Any tokenizer-based counts must be labeled estimated.

No dependency installation or provider-backed experiments are included in implementation. Live comparisons require separate authorization and a stated execution budget.
