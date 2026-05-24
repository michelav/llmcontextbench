from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ctxbench.util.fs import load_json


FILE_MARKER_PATTERN = re.compile(r"^# (?:File|Path): (?P<path>.+?)\s*$")


class RepoQAProvider:
    def __init__(self, *, contexts_dir: str | Path | None = None, dataset_root: str | Path | None = None) -> None:
        if contexts_dir is None and dataset_root is None:
            raise ValueError("RepoQAProvider requires either contexts_dir or dataset_root.")
        self._contexts_dir = _resolve_contexts_dir(contexts_dir=contexts_dir, dataset_root=dataset_root)
        self._cache: dict[str, dict[str, Any]] = {}
        self._text_cache: dict[str, str] = {}

    def list_files(self, workspace_id: str) -> list[dict[str, Any]]:
        payload = self._workspace_payload(workspace_id)
        repository = payload["repository"]
        result: list[dict[str, Any]] = []
        for item in payload["files"]:
            result.append(
                {
                    "repository": item.get("repository") or repository,
                    "path": item["path"],
                    "language": item.get("language"),
                    "symbol_count": _count_symbols(item.get("symbols", [])),
                    "parse_status": item.get("parse_status") or item.get("parseStatus") or "unknown",
                }
            )
        return result

    def list_symbols(
        self,
        workspace_id: str,
        path: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        payload = self._workspace_payload(workspace_id)
        normalized_path = path.strip() if isinstance(path, str) and path.strip() else None
        normalized_kind = kind.strip() if isinstance(kind, str) and kind.strip() else None
        symbols: list[dict[str, Any]] = []
        for item in payload["files"]:
            if normalized_path is not None and item["path"] != normalized_path:
                continue
            for symbol in item.get("symbols", []):
                stripped = _symbol_without_code(symbol, kind=normalized_kind)
                if stripped is not None:
                    symbols.append(stripped)
        return symbols

    def get_symbol(self, workspace_id: str, symbol_id: str) -> dict[str, Any]:
        wanted = symbol_id.strip() if isinstance(symbol_id, str) else ""
        if not wanted:
            raise ValueError("RepoQA symbol lookup requires a non-empty symbol_id.")
        payload = self._workspace_payload(workspace_id)
        for item in payload["files"]:
            for symbol in item.get("symbols", []):
                found = _find_symbol(symbol, wanted)
                if found is not None:
                    return copy.deepcopy(found)
        raise KeyError(f"Unknown RepoQA symbol_id for workspace_id={workspace_id}: {wanted}")

    def read_file(self, workspace_id: str, path: str) -> dict[str, Any]:
        wanted = path.strip() if isinstance(path, str) else ""
        if not wanted:
            raise ValueError("RepoQA read_file requires a non-empty path.")
        payload = self._workspace_payload(workspace_id)
        files_by_path = {item["path"]: item for item in payload["files"]}
        if wanted not in files_by_path:
            raise FileNotFoundError(f"Unknown RepoQA file path for workspace_id={workspace_id}: {wanted}")
        visible = self._visible_files(workspace_id)
        content = visible.get(wanted)
        if content is None:
            item = files_by_path[wanted]
            unparsed_code = item.get("unparsed_code")
            if isinstance(unparsed_code, str) and len(files_by_path) == 1:
                content = unparsed_code
            else:
                raise FileNotFoundError(
                    f"Visible generated context for path={wanted!r} is not available in workspace_id={workspace_id}."
                )
        return {
            "repository": files_by_path[wanted].get("repository") or payload["repository"],
            "path": wanted,
            "language": files_by_path[wanted].get("language"),
            "content": content,
        }

    def resolve_workspace_dir(self, workspace_id: str) -> str:
        path = self._workspace_dir(workspace_id)
        return str(path.resolve())

    def close(self) -> None:
        self._cache.clear()
        self._text_cache.clear()

    def _workspace_payload(self, workspace_id: str) -> dict[str, Any]:
        workspace_dir = self._workspace_dir(workspace_id)
        cache_key = str(workspace_dir.resolve())
        if cache_key not in self._cache:
            parsed_path = workspace_dir / "parsed.json"
            if not parsed_path.exists():
                raise FileNotFoundError(f"Missing RepoQA parsed.json for workspace_id={workspace_id}: {parsed_path}")
            parsed = load_json(parsed_path)
            if not isinstance(parsed, dict):
                raise ValueError(f"RepoQA parsed.json must be a JSON object: {parsed_path}")
            metadata_path = workspace_dir / "metadata.json"
            metadata = load_json(metadata_path) if metadata_path.exists() else {}
            if not isinstance(metadata, dict):
                metadata = {}
            self._cache[cache_key] = _normalize_payload(parsed=parsed, metadata=metadata)
        return self._cache[cache_key]

    def _visible_files(self, workspace_id: str) -> dict[str, str]:
        workspace_dir = self._workspace_dir(workspace_id)
        path = workspace_dir / "code_context.txt"
        cache_key = str(path.resolve())
        if cache_key not in self._text_cache:
            if not path.exists():
                self._text_cache[cache_key] = json.dumps({}, sort_keys=True)
            else:
                self._text_cache[cache_key] = json.dumps(
                    _parse_visible_files(path.read_text(encoding="utf-8")),
                    sort_keys=True,
                )
        return json.loads(self._text_cache[cache_key])

    def _workspace_dir(self, workspace_id: str) -> Path:
        value = workspace_id.strip() if isinstance(workspace_id, str) else ""
        if not value:
            raise ValueError("RepoQA operations require a non-empty workspace_id.")
        path = self._contexts_dir / value
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"Missing RepoQA context directory for workspace_id={value}: {path}")
        return path


def _resolve_contexts_dir(
    *,
    contexts_dir: str | Path | None,
    dataset_root: str | Path | None,
) -> Path:
    if contexts_dir is not None:
        path = Path(contexts_dir)
    else:
        root = Path(dataset_root or "")
        path = root / "context" if (root / "context").exists() else root
    if path.name != "context" and (path / "context").exists():
        path = path / "context"
    return path.resolve()


def _normalize_payload(*, parsed: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    repository = _first_string(parsed.get("repository"), parsed.get("repo"), metadata.get("repo"), metadata.get("repository"))
    files = _coerce_files(parsed=parsed, metadata=metadata, repository=repository)
    return {"repository": repository, "files": files}


def _coerce_files(*, parsed: dict[str, Any], metadata: dict[str, Any], repository: str) -> list[dict[str, Any]]:
    raw_files = parsed.get("files")
    if isinstance(raw_files, list):
        files = [item for item in raw_files if isinstance(item, dict)]
    else:
        path = _first_string(parsed.get("path"), metadata.get("path")) or "unknown"
        language = _first_string(parsed.get("language"), metadata.get("language"))
        code = _first_string(parsed.get("code_context"))
        files = [
            {
                "path": path,
                "language": language,
                "repository": repository,
                "parse_status": "generated",
                "symbols": [],
                "unparsed_code": code,
            }
        ]
    normalized: list[dict[str, Any]] = []
    for file_index, item in enumerate(files):
        path = _first_string(item.get("path"), metadata.get("path")) or f"file-{file_index}"
        file_repository = _first_string(item.get("repository"), item.get("repo"), repository)
        symbols = item.get("symbols") if isinstance(item.get("symbols"), list) else []
        normalized.append(
            {
                "repository": file_repository,
                "path": path,
                "language": _first_string(item.get("language"), metadata.get("language")),
                "parse_status": item.get("parse_status") or item.get("parseStatus") or "unknown",
                "parse_error": item.get("parse_error") or item.get("parseError"),
                "symbols": _normalize_symbols(symbols, path=path, ancestors=[]),
                "unparsed_code": item.get("unparsed_code"),
            }
        )
    return normalized


def _normalize_symbols(raw_symbols: list[Any], *, path: str, ancestors: list[str]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_symbols):
        if not isinstance(item, dict):
            continue
        symbol = copy.deepcopy(item)
        children = symbol.get("children") if isinstance(symbol.get("children"), list) else []
        name = _first_string(symbol.get("name")) or "<anonymous>"
        kind = _first_string(symbol.get("kind")) or "symbol"
        qualified_name = _first_string(symbol.get("qualified_name"), symbol.get("qualifiedName"))
        if not qualified_name:
            qualified_name = ".".join([*ancestors, name]) if ancestors else name
        symbol["path"] = path
        symbol["name"] = name
        symbol["kind"] = kind
        symbol["qualified_name"] = qualified_name
        symbol["symbol_id"] = _first_string(symbol.get("symbol_id"), symbol.get("symbolId")) or _derive_symbol_id(
            path=path,
            kind=kind,
            qualified_name=qualified_name,
            start_line=symbol.get("start_line") or symbol.get("startLine"),
            end_line=symbol.get("end_line") or symbol.get("endLine"),
            sibling_index=index,
        )
        symbol["children"] = _normalize_symbols(children, path=path, ancestors=[*ancestors, name])
        normalized.append(symbol)
    return normalized


def _derive_symbol_id(
    *,
    path: str,
    kind: str,
    qualified_name: str,
    start_line: Any,
    end_line: Any,
    sibling_index: int,
) -> str:
    raw = json.dumps(
        {
            "path": path,
            "kind": kind,
            "qualified_name": qualified_name,
            "start_line": start_line,
            "end_line": end_line,
            "sibling_index": sibling_index,
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"repoqa:{digest}"


def _symbol_without_code(symbol: dict[str, Any], *, kind: str | None) -> dict[str, Any] | None:
    children = [
        child
        for child in (
            _symbol_without_code(item, kind=kind)
            for item in symbol.get("children", [])
            if isinstance(item, dict)
        )
        if child is not None
    ]
    matches = kind is None or symbol.get("kind") == kind
    if not matches and not children:
        return None
    stripped = {key: copy.deepcopy(value) for key, value in symbol.items() if key != "code"}
    stripped["children"] = children if kind is not None else stripped.get("children", [])
    if kind is None:
        stripped["children"] = [
            _symbol_without_code(item, kind=None)
            for item in symbol.get("children", [])
            if isinstance(item, dict)
        ]
    return stripped


def _find_symbol(symbol: dict[str, Any], symbol_id: str) -> dict[str, Any] | None:
    if symbol.get("symbol_id") == symbol_id:
        return symbol
    for child in symbol.get("children", []):
        if isinstance(child, dict):
            found = _find_symbol(child, symbol_id)
            if found is not None:
                return found
    return None


def _count_symbols(symbols: Any) -> int:
    if not isinstance(symbols, list):
        return 0
    total = 0
    for item in symbols:
        if isinstance(item, dict):
            total += 1 + _count_symbols(item.get("children"))
    return total


def _parse_visible_files(text: str) -> dict[str, str]:
    files: dict[str, list[str]] = {}
    current_path: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        match = FILE_MARKER_PATTERN.match(line)
        if match:
            if current_path is not None:
                files[current_path] = _trim_blank_edges(current_lines)
            current_path = match.group("path").strip()
            current_lines = []
            continue
        if current_path is not None:
            current_lines.append(line)
    if current_path is not None:
        files[current_path] = _trim_blank_edges(current_lines)
    return {path: "\n".join(lines) + ("\n" if lines else "") for path, lines in files.items()}


def _trim_blank_edges(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
