from __future__ import annotations

from pathlib import Path

from ctxbench.api.workflows import registry
from ctxbench.phases.export import run_export


def _prepare(root: Path):
    return registry.for_run(root).prepare_responses(root)


def export_command(evals: str | None = None, **options) -> int:
    return run_export(evals, prepare=_prepare, **options)
