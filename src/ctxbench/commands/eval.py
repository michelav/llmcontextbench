from __future__ import annotations

from pathlib import Path

from ctxbench.api.workflows import registry
from ctxbench.phases.evaluation import _load_judges, _load_responses, run_evaluation  # noqa: F401


def _prepare(root: Path):
    return registry.for_run(root).prepare_responses(root)


def eval_command(responses: str | None = None, **options) -> int:
    return run_evaluation(responses, prepare=_prepare, **options)
