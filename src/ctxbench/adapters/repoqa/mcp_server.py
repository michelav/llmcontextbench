from __future__ import annotations

import argparse
from pathlib import Path

from fastmcp import FastMCP

from ctxbench.ai.models.base import ToolResult, ToolSpec
from ctxbench.adapters.repoqa.tools import RepoQAToolService


class RepoQAMCPServer:
    def __init__(
        self,
        *,
        contexts_dir: str | None = None,
        dataset_root: str | None = None,
        provider: object | None = None,
    ) -> None:
        self._service = RepoQAToolService(
            contexts_dir=contexts_dir,
            dataset_root=dataset_root,
            provider=provider,
        )
        self.app = FastMCP(
            name="ctxbench-repoqa",
            instructions=(
                "MCP server for querying generated RepoQA repository context."
                " All tools are read-only and require workspace_id."
            ),
        )
        self._register_tools()
        self._tool_specs = self._service.list_tools()

    def _register_tools(self) -> None:
        @self.app.tool(name="list_files", description="List visible repository files and metadata for a RepoQA workspace.")
        async def list_files(workspace_id: str) -> object:
            return self.call_tool("list_files", {"workspace_id": workspace_id}).content

        @self.app.tool(
            name="list_symbols",
            description=(
                "List code symbols and metadata for a RepoQA workspace. Optional filters: path and kind. "
                "kind='function' searches callable code, including methods; exact parser kinds such as "
                "'method', 'class', and other kinds present in parsed.json may also be used."
            ),
        )
        async def list_symbols(workspace_id: str, path: str | None = None, kind: str | None = None) -> object:
            return self.call_tool(
                "list_symbols",
                {"workspace_id": workspace_id, "path": path, "kind": kind},
            ).content

        @self.app.tool(name="get_symbol", description="Return one RepoQA symbol, including generated visible code.")
        async def get_symbol(workspace_id: str, symbol_id: str) -> object:
            return self.call_tool("get_symbol", {"workspace_id": workspace_id, "symbol_id": symbol_id}).content

        @self.app.tool(name="read_file", description="Read one generated visible file from a RepoQA workspace.")
        async def read_file(workspace_id: str, path: str) -> object:
            return self.call_tool("read_file", {"workspace_id": workspace_id, "path": path}).content

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tool_specs)

    def call_tool(self, name: str, arguments: dict[str, object]) -> ToolResult:
        result = self._service.call_tool(name, arguments)
        metadata = dict(result.metadata)
        metadata["transport"] = "mcp_server"
        return result.model_copy(update={"metadata": metadata})

    def close(self) -> None:
        self._service.close()


def build_repoqa_mcp_server(
    *,
    contexts_dir: str | None = None,
    dataset_root: str | None = None,
    provider: object | None = None,
) -> RepoQAMCPServer:
    return RepoQAMCPServer(contexts_dir=contexts_dir, dataset_root=dataset_root, provider=provider)


def create_mcp(*, contexts_dir: str | None = None, dataset_root: str | None = None) -> FastMCP:
    if contexts_dir is None and dataset_root is None:
        contexts_dir = _default_contexts_dir()
    return build_repoqa_mcp_server(contexts_dir=contexts_dir, dataset_root=dataset_root).app


def _default_contexts_dir() -> str:
    return str((Path(__file__).resolve().parents[4] / "datasets" / "repoqa" / "context").resolve())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the CTXBench RepoQA MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "http", "sse"],
        default="streamable-http",
        help="FastMCP transport to use.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--contexts-dir",
        default=None,
        help="Directory containing RepoQA context artifacts.",
    )
    source.add_argument(
        "--dataset-root",
        default=None,
        help="RepoQA dataset root containing a context directory.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for HTTP-based transports.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP-based transports.",
    )
    parser.add_argument(
        "--path",
        default="/mcp",
        help="Path for streamable HTTP or SSE transports.",
    )
    parser.add_argument(
        "--no-banner",
        action="store_true",
        help="Disable the FastMCP startup banner.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    contexts_dir = args.contexts_dir if args.contexts_dir is not None else None
    dataset_root = args.dataset_root if args.dataset_root is not None else None
    if contexts_dir is None and dataset_root is None:
        contexts_dir = _default_contexts_dir()
    server = build_repoqa_mcp_server(contexts_dir=contexts_dir, dataset_root=dataset_root)
    run_kwargs: dict[str, object] = {"show_banner": not args.no_banner}
    if args.transport in {"streamable-http", "http", "sse"}:
        run_kwargs["host"] = args.host
        run_kwargs["port"] = args.port
        if args.transport in {"streamable-http", "sse"}:
            run_kwargs["path"] = args.path
    try:
        server.app.run(args.transport, **run_kwargs)
    finally:
        server.close()


if __name__ == "__main__":
    main()


mcp = create_mcp()
app = mcp
server = mcp
