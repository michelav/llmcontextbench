from pathlib import Path

import pytest

from ctxbench.ai.runtime import MCPRuntime
from ctxbench.adapters.repoqa.mcp_server import RepoQAMCPServer
from ctxbench.adapters.repoqa.package import RepoQADatasetAdapter
from ctxbench.adapters.repoqa.provider import RepoQAProvider
from ctxbench.adapters.repoqa.tools import REPOQA_OPERATIONS, RepoQAToolService
from ctxbench.benchmark.models import DatasetProvenance, Experiment
from ctxbench.benchmark.runspec_generator import generate_runspecs
from ctxbench.benchmark.surfaces import FullContextSurface, OperationSurface
from ctxbench.benchmark.executor import _resolve_mcp_server


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "repoqa_tools_dataset"
EXPERIMENT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "repoqa_surface_experiment.json"


def test_repoqa_resolves_full_context_and_operation_surfaces() -> None:
    adapter = RepoQADatasetAdapter(FIXTURE)
    full = FullContextSurface()
    operations = OperationSurface(operations=["read_file", "list_files"])

    assert adapter.resolve_surface(full).declaration is full
    resolved = adapter.resolve_surface(operations)
    assert resolved.declaration is operations
    assert resolved.operations == ("read_file", "list_files")
    with pytest.raises(ValueError, match="Unknown RepoQA operations: missing"):
        adapter.resolve_surface(OperationSurface(operations=["missing"]))


@pytest.mark.parametrize("operation", REPOQA_OPERATIONS)
def test_each_repoqa_operation_can_be_selected_individually(operation: str) -> None:
    service = RepoQAToolService(contexts_dir=str(FIXTURE / "context"), allowed_operations=[operation])
    assert [tool.name for tool in service.list_tools()] == [operation]


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("list_files", {}),
        ("list_symbols", {}),
        ("get_symbol", {"symbol_id": "repoqa-workspace-1:src/example.py:greet"}),
        ("read_file", {"path": "src/example.py"}),
    ],
)
def test_each_repoqa_operation_runs_against_fixture(
    operation: str,
    arguments: dict[str, str],
) -> None:
    service = RepoQAToolService(contexts_dir=str(FIXTURE / "context"), allowed_operations=[operation])
    call_arguments = {"workspace_id": "repoqa-workspace-1", **arguments}
    if operation == "get_symbol":
        provider = RepoQAProvider(contexts_dir=str(FIXTURE / "context"))
        try:
            call_arguments["symbol_id"] = provider.list_symbols("repoqa-workspace-1")[0]["children"][0]["symbol_id"]
        finally:
            provider.close()
    try:
        result = service.call_tool(operation, call_arguments)
    finally:
        service.close()

    assert result.is_error is False


def test_service_rejects_disallowed_known_tool_before_handler_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    service = RepoQAToolService(contexts_dir=str(FIXTURE / "context"), allowed_operations=["list_files"])
    called = False

    def forbidden(_arguments: dict[str, object]) -> list[object]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(service, "_call_read_file", forbidden)
    with pytest.raises(KeyError, match="Unselected"):
        service.call_tool("read_file", {"workspace_id": "repoqa-workspace-1", "path": "src/example.py"})
    assert called is False


def test_mcp_subset_hides_and_rejects_omitted_tools() -> None:
    server = RepoQAMCPServer(contexts_dir=str(FIXTURE / "context"), allowed_operations=["read_file"])
    runtime = MCPRuntime.for_local_server(server)
    try:
        assert [tool.name for tool in runtime.list_tools()] == ["read_file"]
        with pytest.raises(KeyError, match="Unselected"):
            server.call_tool("list_files", {"workspace_id": "repoqa-workspace-1"})
    finally:
        runtime.close()


def test_none_allow_list_preserves_standalone_tool_order() -> None:
    service = RepoQAToolService(contexts_dir=str(FIXTURE / "context"))
    server = RepoQAMCPServer(contexts_dir=str(FIXTURE / "context"))
    expected = list(REPOQA_OPERATIONS)
    runtime = MCPRuntime.for_local_server(server)
    try:
        assert [tool.name for tool in service.list_tools()] == expected
        assert [tool.name for tool in runtime.list_tools()] == expected
    finally:
        runtime.close()


@pytest.mark.parametrize("allowed_operations", [[], ["list_files", "list_files"], ["unknown"]])
def test_invalid_allow_lists_fail_at_construction(allowed_operations: list[str]) -> None:
    with pytest.raises(ValueError):
        RepoQAToolService(contexts_dir=str(FIXTURE / "context"), allowed_operations=allowed_operations)


def test_repoqa_planning_and_executor_preserve_operation_allow_list(tmp_path: Path) -> None:
    experiment = Experiment.model_validate_json(EXPERIMENT_FIXTURE.read_text(encoding="utf-8"))
    adapter = RepoQADatasetAdapter(FIXTURE)
    trials = generate_runspecs(
        experiment,
        tmp_path,
        adapter,
        DatasetProvenance(id="ctxbench/repoqa", version="fixture", materialized_path=str(FIXTURE)),
    )

    assert len(trials) == 2
    inline_trial = next(trial for trial in trials if trial.configurationId == "inline-code-full")
    mcp_trial = next(trial for trial in trials if trial.configurationId == "local-mcp-repoqa-ops")
    assert inline_trial.surfaceSpec == {"type": "full_context"}
    assert mcp_trial.surfaceSpec["operations"] == list(REPOQA_OPERATIONS)

    server = _resolve_mcp_server(adapter, mcp_trial)
    try:
        assert [tool.name for tool in server.list_tools()] == list(REPOQA_OPERATIONS)
    finally:
        server.close()


@pytest.mark.parametrize("operations", [[], ["unknown"]])
def test_planning_rejects_invalid_operations(tmp_path, operations):
    import json
    data = json.loads(EXPERIMENT_FIXTURE.read_text())
    data["surfaces"]["repoqa-ops"]["operations"] = operations
    with pytest.raises(ValueError):
        experiment = Experiment.model_validate(data)
        generate_runspecs(experiment, tmp_path, RepoQADatasetAdapter(FIXTURE),
            DatasetProvenance(id="ctxbench/repoqa", version="fixture", materialized_path=str(FIXTURE)))


@pytest.mark.parametrize("operation", REPOQA_OPERATIONS)
def test_fastmcp_single_operation_discovery_invocation_and_rejection(operation):
    import asyncio
    from fastmcp import Client
    server = RepoQAMCPServer(contexts_dir=str(FIXTURE / "context"), allowed_operations=[operation])
    arguments = {"workspace_id": "repoqa-workspace-1"}
    if operation == "read_file":
        arguments["path"] = "src/example.py"
    if operation == "get_symbol":
        arguments["symbol_id"] = "existing-helper-id"

    async def check():
        async with Client(server.app) as client:
            assert [tool.name for tool in await client.list_tools()] == [operation]
            result = await client.call_tool(operation, arguments)
            assert not result.is_error
            for omitted in set(REPOQA_OPERATIONS) - {operation}:
                with pytest.raises(KeyError):
                    server.call_tool(omitted, arguments)
                # FastMCP owns the transport-specific exception type/message.
                with pytest.raises(Exception):
                    await client.call_tool(omitted, arguments)
    try:
        asyncio.run(check())
    finally:
        server.close()
