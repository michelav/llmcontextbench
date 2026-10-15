from __future__ import annotations

from time import perf_counter
from copy import deepcopy
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

FIND_SYMBOL_SCHEMA = {
    "type": "object",
    "properties": {
        "workspace_id": {"type": "string"},
        "query": {"type": "string"},
        "k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
    },
    "required": ["workspace_id", "query"],
    "additionalProperties": False,
}

FIND_SYMBOL_DESCRIPTION = (
    "Search a RepoQA workspace for the code symbols that best match a description of what the code does. "
    "Pass the description (or key words from it) as query. Returns the top k symbols (default 5, at most 20), "
    "best first, each with symbol_id, name, path and complete code."
)

REPOQA_OPERATIONS = ("list_files", "list_symbols", "get_symbol", "read_file")

REPOQA_LEAN_OPERATIONS = tuple(name + "_lean" for name in REPOQA_OPERATIONS)
REPOQA_TASK_OPERATIONS = ("find_symbol",)
REPOQA_ALL_OPERATIONS = REPOQA_OPERATIONS + REPOQA_LEAN_OPERATIONS + REPOQA_TASK_OPERATIONS


def normalize_allowed_operations(allowed_operations: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if allowed_operations is None:
        return REPOQA_OPERATIONS
    selected = tuple(allowed_operations)
    if not selected:
        raise ValueError("RepoQA allowed_operations must contain at least one operation.")
    if len(selected) != len(set(selected)):
        raise ValueError("RepoQA allowed_operations must not contain duplicate operation names.")
    unknown = [name for name in selected if name not in REPOQA_ALL_OPERATIONS]
    if unknown:
        raise ValueError(f"Unknown RepoQA operations: {', '.join(unknown)}")
    return tuple(name for name in REPOQA_ALL_OPERATIONS if name in selected)


def list_repoqa_tool_specs(*, include_lean: bool = False) -> list[ToolSpec]:
    defaults = [
        ToolSpec(
            name="list_files",
            description="List visible repository files and metadata for a RepoQA workspace.",
            input_schema=WORKSPACE_SCHEMA,
        ),
        ToolSpec(
            name="list_symbols",
            description=(
                "List code symbols and metadata for a RepoQA workspace. Optional filters: path and kind. "
                "path may be an exact file path or a directory prefix such as 'src' or 'src/package'. "
                "kind='function' searches callable code, including methods; exact parser kinds such as "
                "'method', 'class', and other kinds present in parsed.json may also be used."
            ),
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

    descriptions = (
        "List visible file paths for a RepoQA workspace.",
        "List flat symbols with stable IDs, qualified names, kinds and documentation. Optional path (file or directory) and kind filters; function includes methods.",
        "Return complete visible code for one RepoQA symbol.",
        "Return only the visible file content for a RepoQA workspace.",
    )
    if not include_lean:
        return defaults
    task = [ToolSpec(name="find_symbol", description=FIND_SYMBOL_DESCRIPTION, input_schema=FIND_SYMBOL_SCHEMA)]
    lean_symbols_schema = deepcopy(LIST_SYMBOLS_SCHEMA)
    for field in ("path", "kind"):
        lean_symbols_schema["properties"][field] = {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}
    return defaults + [ToolSpec(name=spec.name + "_lean", description=description,
                                input_schema=lean_symbols_schema if spec.name == "list_symbols" else spec.input_schema)
                       for spec, description in zip(defaults, descriptions)] + task


class RepoQAToolService:
    def __init__(
        self,
        *,
        contexts_dir: str | None = None,
        dataset_root: str | None = None,
        provider: RepoQAProvider | None = None,
        allowed_operations: list[str] | None = None,
    ) -> None:
        self._provider = provider or RepoQAProvider(contexts_dir=contexts_dir, dataset_root=dataset_root)
        self._allowed_operations = normalize_allowed_operations(allowed_operations)
        specs = {spec.name: spec for spec in list_repoqa_tool_specs(include_lean=True)}
        self._tools = [specs[name] for name in self._allowed_operations]
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "list_files": self._call_list_files,
            "list_symbols": self._call_list_symbols,
            "get_symbol": self._call_get_symbol,
            "read_file": self._call_read_file,
            "find_symbol": self._call_find_symbol,
        }
        for name in REPOQA_LEAN_OPERATIONS:
            self._handlers[name] = self._lean_handler(name)
        self._handlers = {name: self._handlers[name] for name in self._allowed_operations}

    def _lean_handler(self, name):
        def call(arguments):
            workspace = _require_string(arguments, "workspace_id")
            method = getattr(self._provider, name)
            if name == "list_symbols_lean":
                return method(workspace, path=_optional_string(arguments, "path"),
                              kind=_optional_string(arguments, "kind"))
            if name == "get_symbol_lean":
                return method(workspace, _require_string(arguments, "symbol_id"))
            if name == "read_file_lean":
                return method(workspace, _require_string(arguments, "path"))
            return method(workspace)
        return call

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            raise KeyError(f"Unselected or unknown RepoQA tool: {name}")
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

    def _call_find_symbol(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        k = arguments.get("k", 5)
        if k is None:
            k = 5
        if isinstance(k, bool) or not isinstance(k, int):
            raise ValueError("RepoQA find_symbol requires 'k' to be an integer when provided.")
        return self._provider.find_symbol(_require_string(arguments, "workspace_id"),
                                          _require_string(arguments, "query"), k)

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
