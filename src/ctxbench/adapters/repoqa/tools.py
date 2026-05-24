from __future__ import annotations

from time import perf_counter
from typing import Any, Callable

from ctxbench.ai.models.base import ToolResult, ToolSpec
from ctxbench.adapters.repoqa.provider import RepoQAProvider


WORKSPACE_SCHEMA = {
    "type": "object",
    "properties": {
        "workspace_id": {"type": "string"},
    },
    "required": ["workspace_id"],
    "additionalProperties": False,
}

LIST_SYMBOLS_SCHEMA = {
    "type": "object",
    "properties": {
        "workspace_id": {"type": "string"},
        "path": {"type": "string"},
        "kind": {"type": "string"},
    },
    "required": ["workspace_id"],
    "additionalProperties": False,
}

GET_SYMBOL_SCHEMA = {
    "type": "object",
    "properties": {
        "workspace_id": {"type": "string"},
        "symbol_id": {"type": "string"},
    },
    "required": ["workspace_id", "symbol_id"],
    "additionalProperties": False,
}

READ_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "workspace_id": {"type": "string"},
        "path": {"type": "string"},
    },
    "required": ["workspace_id", "path"],
    "additionalProperties": False,
}


def list_repoqa_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="list_files",
            description="List visible repository files and metadata for a RepoQA workspace.",
            input_schema=WORKSPACE_SCHEMA,
        ),
        ToolSpec(
            name="list_symbols",
            description="List code symbols and metadata for a RepoQA workspace, optionally filtered by file path or kind.",
            input_schema=LIST_SYMBOLS_SCHEMA,
        ),
        ToolSpec(
            name="get_symbol",
            description="Return one RepoQA symbol, including its generated visible code.",
            input_schema=GET_SYMBOL_SCHEMA,
        ),
        ToolSpec(
            name="read_file",
            description="Read one generated visible file from a RepoQA workspace.",
            input_schema=READ_FILE_SCHEMA,
        ),
    ]


class RepoQAToolService:
    def __init__(
        self,
        *,
        contexts_dir: str | None = None,
        dataset_root: str | None = None,
        provider: RepoQAProvider | None = None,
    ) -> None:
        self._provider = provider or RepoQAProvider(contexts_dir=contexts_dir, dataset_root=dataset_root)
        self._tools = list_repoqa_tool_specs()
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "list_files": self._call_list_files,
            "list_symbols": self._call_list_symbols,
            "get_symbol": self._call_get_symbol,
            "read_file": self._call_read_file,
        }

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            raise KeyError(f"Unknown RepoQA tool: {name}")
        started_at = perf_counter()
        workspace_id = _require_string(arguments, "workspace_id")
        try:
            content = handler(arguments)
            is_error = False
        except (FileNotFoundError, KeyError, ValueError) as exc:
            content = {"error": str(exc)}
            is_error = True
        duration_ms = max(0, int((perf_counter() - started_at) * 1000))
        return ToolResult(
            name=name,
            content=content,
            is_error=is_error,
            metadata={
                "server_event": {
                    "toolName": name,
                    "arguments": dict(arguments),
                    "workspace_id": workspace_id,
                    "durationMs": duration_ms,
                }
            },
        )

    def close(self) -> None:
        self._provider.close()

    def _call_list_files(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        return self._provider.list_files(_require_string(arguments, "workspace_id"))

    def _call_list_symbols(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        return self._provider.list_symbols(
            _require_string(arguments, "workspace_id"),
            path=_optional_string(arguments, "path"),
            kind=_optional_string(arguments, "kind"),
        )

    def _call_get_symbol(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._provider.get_symbol(
            _require_string(arguments, "workspace_id"),
            _require_string(arguments, "symbol_id"),
        )

    def _call_read_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._provider.read_file(
            _require_string(arguments, "workspace_id"),
            _require_string(arguments, "path"),
        )


def _require_string(arguments: dict[str, Any], field_name: str) -> str:
    value = arguments.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"RepoQA tools require a non-empty '{field_name}' argument.")
    return value.strip()


def _optional_string(arguments: dict[str, Any], field_name: str) -> str | None:
    value = arguments.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"RepoQA tools require '{field_name}' to be a string when provided.")
    return value.strip() or None
