from __future__ import annotations

from pathlib import Path

from ctxbench.ai.runtime import MCPRuntime
from ctxbench.adapters.repoqa.mcp_server import RepoQAMCPServer
from ctxbench.adapters.repoqa.package import RepoQADatasetAdapter
from ctxbench.adapters.repoqa.provider import RepoQAProvider
from ctxbench.adapters.repoqa.tools import RepoQAToolService, list_repoqa_tool_specs


def _dataset_root() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "repoqa_tools_dataset"


def _contexts_dir() -> Path:
    return _dataset_root() / "context"


def test_provider_lists_files_symbols_and_reads_visible_file() -> None:
    provider = RepoQAProvider(contexts_dir=_contexts_dir())

    files = provider.list_files("repoqa-workspace-1")
    symbols = provider.list_symbols("repoqa-workspace-1")
    function_symbols = provider.list_symbols("repoqa-workspace-1", kind="function")
    helper = provider.get_symbol("repoqa-workspace-1", "existing-helper-id")
    visible_file = provider.read_file("repoqa-workspace-1", "src/example.py")

    assert files == [
        {
            "repository": "example/repo",
            "path": "src/example.py",
            "language": "python",
            "symbol_count": 3,
            "parse_status": "ok",
        },
        {
            "repository": "example/repo",
            "path": "src/hidden.py",
            "language": "python",
            "symbol_count": 0,
            "parse_status": "fallback",
        },
    ]
    assert "code" not in symbols[0]
    assert symbols[0]["path"] == "src/example.py"
    assert symbols[0]["symbol_id"].startswith("repoqa:")
    assert symbols[0]["children"][0]["qualified_name"] == "Greeter.greet"
    assert symbols[0]["children"][0]["symbol_id"].startswith("repoqa:")
    assert [item["name"] for item in function_symbols] == ["Greeter", "helper"]
    assert [item["name"] for item in function_symbols[0]["children"]] == ["greet"]
    assert helper["code"].startswith("def helper")
    assert visible_file["content"].startswith("class Greeter")
    assert "THIS FALLBACK MUST NOT BE USED" not in visible_file["content"]


def test_provider_uses_only_allowed_artifacts(monkeypatch) -> None:
    original_read_text = Path.read_text
    read_paths: list[str] = []

    def spy_read_text(self: Path, *args: object, **kwargs: object) -> str:
        read_paths.append(str(self))
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read_text)
    provider = RepoQAProvider(contexts_dir=_contexts_dir())

    provider.list_files("repoqa-workspace-1")
    provider.read_file("repoqa-workspace-1", "src/example.py")

    assert any(path.endswith("parsed.json") for path in read_paths)
    assert any(path.endswith("metadata.json") for path in read_paths)
    assert any(path.endswith("code_context.txt") for path in read_paths)
    assert not any(path.endswith("oracle.json") for path in read_paths)
    assert not any(path.endswith("native_task.json") for path in read_paths)
    assert not any(path.endswith("repoqa_prompt.txt") for path in read_paths)
    assert not any("/raw/" in path for path in read_paths)


def test_tool_service_specs_validation_metadata_and_errors() -> None:
    service = RepoQAToolService(contexts_dir=str(_contexts_dir()))

    tools = service.list_tools()
    names = [tool.name for tool in tools]
    error = service.call_tool(
        "get_symbol",
        {"workspace_id": "repoqa-workspace-1", "symbol_id": "missing"},
    )
    result = service.call_tool("list_files", {"workspace_id": "repoqa-workspace-1"})

    assert names == ["list_files", "list_symbols", "get_symbol", "read_file"]
    assert names == [tool.name for tool in list_repoqa_tool_specs()]
    assert all(tool.input_schema["additionalProperties"] is False for tool in tools)
    assert tools[0].input_schema["required"] == ["workspace_id"]
    assert tools[2].input_schema["required"] == ["workspace_id", "symbol_id"]
    assert result.metadata["server_event"]["toolName"] == "list_files"
    assert result.metadata["server_event"]["arguments"] == {"workspace_id": "repoqa-workspace-1"}
    assert result.metadata["server_event"]["workspace_id"] == "repoqa-workspace-1"
    assert isinstance(result.metadata["server_event"]["durationMs"], int)
    assert error.is_error is True
    assert "Unknown RepoQA symbol_id" in error.content["error"]


def test_adapter_exposes_tools_mcp_server_and_instruction_fallback(tmp_path: Path) -> None:
    adapter = RepoQADatasetAdapter(_dataset_root())
    service = adapter.tool_provider()
    server = adapter.mcp_server()

    assert isinstance(service, RepoQAToolService)
    assert isinstance(server, RepoQAMCPServer)
    assert adapter.dataset_instructions() == "Use RepoQA tools to inspect the generated repository context."

    md_root = tmp_path / "repoqa-md"
    md_root.mkdir()
    (md_root / "tasks.json").write_text((_dataset_root() / "tasks.json").read_text(encoding="utf-8"), encoding="utf-8")
    (md_root / "tasks.instance.json").write_text(
        (_dataset_root() / "tasks.instance.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (md_root / "dataset-instructions.md").write_text("Markdown fallback instructions\n", encoding="utf-8")
    assert RepoQADatasetAdapter(md_root).dataset_instructions() == "Markdown fallback instructions"


def test_local_mcp_runtime_exposes_repoqa_tools_and_calls_symbol() -> None:
    server = RepoQAMCPServer(contexts_dir=str(_contexts_dir()))
    runtime = MCPRuntime.for_local_server(server)
    try:
        tools = runtime.list_tools()
        symbols = server.call_tool("list_symbols", {"workspace_id": "repoqa-workspace-1"}).content
        child_symbol_id = symbols[0]["children"][0]["symbol_id"]
        result = runtime.call_tool(
            "get_symbol",
            {"workspace_id": "repoqa-workspace-1", "symbol_id": child_symbol_id},
        )
    finally:
        runtime.close()

    assert [tool.name for tool in tools] == ["list_files", "list_symbols", "get_symbol", "read_file"]
    schemas = {tool.name: tool.input_schema for tool in tools}
    assert "workspace_id" in schemas["list_files"]["required"]
    assert "symbol_id" in schemas["get_symbol"]["required"]
    assert result.content["name"] == "greet"
    assert "return" in result.content["code"]


def test_repoqa_dataset_legacy_modules_reexport_adapter_symbols() -> None:
    from ctxbench.adapters.repoqa.mcp_server import RepoQAMCPServer as AdapterMCPServer
    from ctxbench.adapters.repoqa.provider import RepoQAProvider as AdapterProvider
    from ctxbench.adapters.repoqa.tools import RepoQAToolService as AdapterToolService
    from ctxbench.datasets.repoqa.mcp_server import RepoQAMCPServer as LegacyMCPServer
    from ctxbench.datasets.repoqa.provider import RepoQAProvider as LegacyProvider
    from ctxbench.datasets.repoqa.tools import RepoQAToolService as LegacyToolService

    assert LegacyProvider is AdapterProvider
    assert LegacyToolService is AdapterToolService
    assert LegacyMCPServer is AdapterMCPServer
