from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    assert "code" not in visible_file
    assert "THIS FALLBACK MUST NOT BE USED" not in visible_file["content"]


@pytest.mark.parametrize(
    "marker",
    [
        "# Path: src/example.py",
        "// File: src/example.py",
        "-- File: src/example.py",
        "/* File: src/example.py */",
        "<!-- Path: src/example.py -->",
    ],
)
def test_provider_read_file_supports_visible_file_marker_styles(tmp_path: Path, marker: str) -> None:
    workspace = tmp_path / "context" / "repoqa-workspace-marker"
    workspace.mkdir(parents=True)
    (workspace / "parsed.json").write_text(
        json.dumps(
            {
                "repository": "example/repo",
                "files": [
                    {
                        "repository": "example/repo",
                        "path": "src/example.py",
                        "language": "python",
                        "symbols": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (workspace / "metadata.json").write_text(json.dumps({"repository": "example/repo"}), encoding="utf-8")
    (workspace / "code_context.txt").write_text(
        "\n".join(
            [
                "# Repository: example/repo",
                "// Repo: example/repo",
                marker,
                "",
                "def visible():",
                "    return 'from code_context'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (workspace / "oracle.json").write_text(json.dumps({"answer": "must not be read"}), encoding="utf-8")
    (workspace / "native_task.json").write_text(json.dumps({"name": "must not be read"}), encoding="utf-8")

    result = RepoQAProvider(contexts_dir=tmp_path / "context").read_file(
        "repoqa-workspace-marker",
        "src/example.py",
    )

    assert result["content"] == "def visible():\n    return 'from code_context'\n"
    assert "code" not in result


def test_provider_symbol_kind_function_includes_methods() -> None:
    provider = RepoQAProvider(contexts_dir=_contexts_dir())

    function_symbols = provider.list_symbols("repoqa-workspace-1", kind="function")

    assert [item["name"] for item in function_symbols] == ["Greeter", "helper"]
    assert function_symbols[0]["kind"] == "class"
    assert "code" not in function_symbols[0]
    assert [(item["name"], item["kind"]) for item in function_symbols[0]["children"]] == [("greet", "method")]
    assert function_symbols[1]["kind"] == "function"


def test_provider_list_symbols_path_accepts_directory_prefix() -> None:
    provider = RepoQAProvider(contexts_dir=_contexts_dir())

    symbols = provider.list_symbols("repoqa-workspace-1", path="src")

    assert [item["path"] for item in symbols] == ["src/example.py", "src/example.py"]
    assert [item["name"] for item in symbols] == ["Greeter", "helper"]


def test_provider_list_symbols_path_strips_trailing_slash() -> None:
    provider = RepoQAProvider(contexts_dir=_contexts_dir())

    without_slash = provider.list_symbols("repoqa-workspace-1", path="src")
    with_slash = provider.list_symbols("repoqa-workspace-1", path="src/")

    assert with_slash == without_slash


def test_provider_list_symbols_path_exact_file_still_works() -> None:
    provider = RepoQAProvider(contexts_dir=_contexts_dir())

    symbols = provider.list_symbols("repoqa-workspace-1", path="src/example.py")

    assert [item["name"] for item in symbols] == ["Greeter", "helper"]
    assert {item["path"] for item in symbols} == {"src/example.py"}


def test_provider_list_symbols_path_unrelated_prefix_returns_empty() -> None:
    provider = RepoQAProvider(contexts_dir=_contexts_dir())

    assert provider.list_symbols("repoqa-workspace-1", path="other") == []
    assert provider.list_symbols("repoqa-workspace-1", path="sr") == []


def test_provider_list_symbols_path_prefix_preserves_kind_function_filtering() -> None:
    provider = RepoQAProvider(contexts_dir=_contexts_dir())

    function_symbols = provider.list_symbols("repoqa-workspace-1", path="src", kind="function")

    assert [item["name"] for item in function_symbols] == ["Greeter", "helper"]
    assert [(item["name"], item["kind"]) for item in function_symbols[0]["children"]] == [("greet", "method")]
    assert function_symbols[1]["kind"] == "function"


def test_provider_symbol_kind_method_is_exact() -> None:
    provider = RepoQAProvider(contexts_dir=_contexts_dir())

    method_symbols = provider.list_symbols("repoqa-workspace-1", kind="method")

    assert [item["name"] for item in method_symbols] == ["Greeter"]
    assert [(item["name"], item["kind"]) for item in method_symbols[0]["children"]] == [("greet", "method")]


def test_provider_symbol_kind_class_is_exact() -> None:
    provider = RepoQAProvider(contexts_dir=_contexts_dir())

    class_symbols = provider.list_symbols("repoqa-workspace-1", kind="class")

    assert [item["name"] for item in class_symbols] == ["Greeter"]
    assert class_symbols[0]["kind"] == "class"
    assert class_symbols[0]["children"] == []


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
