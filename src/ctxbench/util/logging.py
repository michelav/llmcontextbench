from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, TextIO


CANONICAL_PHASES = {"DATASET", "PLAN", "EXECUTE", "EVAL", "EXPORT", "METRICS", "STATUS"}
_VERBOSE_LEVELS = {"DEBUG", "INFO"}


def _field_value(value: object) -> str | None:
    if value is None:
        return None
    if value == "":
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_field_value(item) for item in value]
        items = [item for item in items if item]
        if not items:
            return None
        return ",".join(items)
    if isinstance(value, dict) and not value:
        return None
    return str(value)


def _format_field(value: object) -> str | None:
    text = _field_value(value)
    if text is None:
        return None
    if any(char.isspace() for char in text) or '"' in text:
        return '"' + text.replace('"', '\\"') + '"'
    return text


def _get_value(source: object, *names: str) -> object | None:
    for name in names:
        value: object | None = None
        if isinstance(source, dict):
            value = source.get(name)
        else:
            value = getattr(source, name, None)
        if value is not None:
            return value
    return None


def _metadata(source: object) -> dict[str, Any]:
    metadata = _get_value(source, "metadata")
    if metadata is None:
        return {}
    if isinstance(metadata, dict):
        return metadata
    if hasattr(metadata, "model_dump"):
        dumped = metadata.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _first(source: object, metadata: dict[str, Any], *names: str) -> object | None:
    value = _get_value(source, *names)
    if value is not None:
        return value
    for name in names:
        if name in metadata and metadata[name] is not None:
            return metadata[name]
    return None


def trial_log_context(source: object) -> dict[str, object]:
    metadata = _metadata(source)
    context = {
        "experimentId": _first(source, metadata, "experimentId"),
        "trialId": _first(source, metadata, "trialId"),
        "instanceId": _first(source, metadata, "instanceId", "instance_id"),
        "taskId": _first(source, metadata, "taskId"),
        "provider": _first(source, metadata, "provider"),
        "modelId": _first(source, metadata, "modelId"),
        "modelName": _first(source, metadata, "modelName"),
        "strategy": _first(source, metadata, "strategy"),
        "format": _first(source, metadata, "format"),
        "repeatIndex": _first(source, metadata, "repeatIndex"),
        "validationType": _first(source, metadata, "validationType", "validation_type"),
    }
    return {key: value for key, value in context.items() if value is not None}


def dataset_log_context(source: object, *, adapter: str | None = None, dataset_name: str | None = None) -> dict[str, object]:
    context = {
        "datasetId": _get_value(source, "id", "identity"),
        "datasetVersion": _get_value(source, "version"),
        "datasetName": dataset_name or _get_value(source, "name"),
        "datasetOrigin": _get_value(source, "origin"),
        "resolvedRevision": _get_value(source, "resolved_revision", "resolvedRevision"),
        "contentHash": _get_value(source, "content_hash", "contentHash"),
        "materializedPath": _get_value(source, "materialized_path", "materializedPath"),
        "adapter": adapter,
    }
    return {key: value for key, value in context.items() if value is not None}


def evaluation_log_context(source: object, **extra: object) -> dict[str, object]:
    context = trial_log_context(source)
    for key in (
        "evaluationMethod",
        "judgeId",
        "judgeModel",
        "judgeRole",
        "contextBlocks",
        "missingBlocks",
    ):
        value = extra.get(key)
        if value is not None:
            context[key] = value
    return context


@dataclass
class ProgressTracker:
    total: int
    enabled: bool = False
    description: str = "Processing runs"
    stream: TextIO | None = None
    width: int = 24
    count: int = 0

    def __post_init__(self) -> None:
        self.enabled = self.enabled and self.total > 1
        if self.stream is None:
            self.stream = sys.stderr

    def start(self) -> None:
        if self.enabled:
            self._render()

    def advance(self) -> None:
        if not self.enabled:
            return
        self.count += 1
        self._render()
        if self.count >= self.total:
            self.stream.write("\n")
            self.stream.flush()

    def clear(self) -> None:
        if not self.enabled:
            return
        self.stream.write("\r" + (" " * 120) + "\r")
        self.stream.flush()

    def redraw(self) -> None:
        if self.enabled and self.count < self.total:
            self._render()

    def _render(self) -> None:
        ratio = 0 if self.total <= 0 else min(max(self.count / self.total, 0), 1)
        filled = int(self.width * ratio)
        bar = "█" * filled + " " * (self.width - filled)
        percent = int(ratio * 100)
        self.stream.write(
            f"\r{self.description}: {percent:>3}%|{bar}| {self.count}/{self.total}"
        )
        self.stream.flush()


class PhaseLogger:
    def __init__(
        self,
        *,
        verbose: bool = False,
        progress: ProgressTracker | None = None,
        stream: TextIO | None = None,
    ) -> None:
        self.verbose = verbose
        self.progress = progress
        self.stream = stream or sys.stderr

    def event(self, level: str, phase: str, eventName: str, message: str, **fields: object) -> None:
        level = level.upper()
        phase = phase.upper()
        if phase not in CANONICAL_PHASES:
            raise ValueError(f"Unknown log phase: {phase}")
        if level in _VERBOSE_LEVELS and not self.verbose:
            return
        self._emit(level, phase, eventName, message, fields)

    def debug(self, phase: str, eventName: str, message: str, **fields: object) -> None:
        self.event("DEBUG", phase, eventName, message, **fields)

    def info(self, phase: str, eventName: str, message: str, **fields: object) -> None:
        self.event("INFO", phase, eventName, message, **fields)

    def warn(self, phase: str, eventName: str, message: str, **fields: object) -> None:
        self.event("WARN", phase, eventName, message, **fields)

    def error(self, phase: str, eventName: str, message: str, **fields: object) -> None:
        self.event("ERROR", phase, eventName, message, **fields)

    def phase(self, label: str, message: str, **fields: object) -> None:
        # Compatibility for legacy internal commands. Public commands should use event().
        phase = label.upper() if label.upper() in CANONICAL_PHASES else "STATUS"
        self.info(phase, label.lower(), message, **fields)

    def _emit(self, level: str, phase: str, eventName: str, message: str, fields: dict[str, object]) -> None:
        if self.progress is not None:
            self.progress.clear()
        rendered_fields = [f"phase={phase}", f"eventName={eventName}"]
        for key, value in fields.items():
            rendered = _format_field(value)
            if rendered is not None:
                rendered_fields.append(f"{key}={rendered}")
        context = " ".join(rendered_fields)
        self.stream.write(f"[{level}] {context} {message}\n")
        self.stream.flush()
        if self.progress is not None:
            self.progress.redraw()
