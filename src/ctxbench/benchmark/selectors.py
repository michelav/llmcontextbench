from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunSelector:
    provider: tuple[str, ...] = ()
    model: tuple[str, ...] = ()
    instance: tuple[str, ...] = ()
    task: tuple[str, ...] = ()
    strategy: tuple[str, ...] = ()
    format: tuple[str, ...] = ()
    repetition: tuple[int, ...] = ()
    status: tuple[str, ...] = ()
    trial_id: tuple[str, ...] = ()
    not_provider: tuple[str, ...] = ()
    not_model: tuple[str, ...] = ()
    not_instance: tuple[str, ...] = ()
    not_task: tuple[str, ...] = ()
    not_strategy: tuple[str, ...] = ()
    not_format: tuple[str, ...] = ()
    not_repetition: tuple[int, ...] = ()
    not_status: tuple[str, ...] = ()


def matches_runspec(item: Any, selector: RunSelector) -> bool:
    return _matches_common(item, selector)


def matches_run_result(item: Any, selector: RunSelector) -> bool:
    if selector.status and _field(item, "status") not in selector.status:
        return False
    if selector.not_status and _field(item, "status") in selector.not_status:
        return False
    return _matches_common(item, selector)


def _matches_common(item: Any, selector: RunSelector) -> bool:
    if selector.trial_id and _field(item, "trialId") not in selector.trial_id:
        return False
    if selector.provider and _field(item, "provider") not in selector.provider:
        return False
    if selector.model:
        model_id = _field(item, "modelId")
        model_name = _field(item, "modelName")
        if model_id not in selector.model and model_name not in selector.model:
            return False
    if selector.instance and _field(item, "instanceId") not in selector.instance:
        return False
    if selector.task and _field(item, "taskId") not in selector.task:
        return False
    if selector.strategy and _field(item, "strategy") not in selector.strategy:
        return False
    if selector.format and _field(item, "format") not in selector.format:
        return False
    if selector.repetition and _field(item, "repeatIndex") not in selector.repetition:
        return False
    if selector.not_provider and _field(item, "provider") in selector.not_provider:
        return False
    if selector.not_model:
        model_id = _field(item, "modelId")
        model_name = _field(item, "modelName")
        if model_id in selector.not_model or model_name in selector.not_model:
            return False
    if selector.not_instance and _field(item, "instanceId") in selector.not_instance:
        return False
    if selector.not_task and _field(item, "taskId") in selector.not_task:
        return False
    if selector.not_strategy and _field(item, "strategy") in selector.not_strategy:
        return False
    if selector.not_format and _field(item, "format") in selector.not_format:
        return False
    if selector.not_repetition and _field(item, "repeatIndex") in selector.not_repetition:
        return False
    return True


def _field(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        if name == "modelName" and "modelName" not in item:
            return item.get("model")
        return item.get(name)
    return getattr(item, name, None)


def load_ids_from_stdin() -> tuple[str, ...]:
    lines = sys.stdin.read().splitlines()
    return tuple(line.strip() for line in lines if line.strip())


def load_ids_from_file(path: str) -> tuple[str, ...]:
    text = Path(path).read_text(encoding="utf-8")
    return tuple(line.strip() for line in text.splitlines() if line.strip())
