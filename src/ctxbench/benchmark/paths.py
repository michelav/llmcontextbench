from __future__ import annotations

from pathlib import Path

from ctxbench.benchmark.models import Experiment


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base_dir / path).resolve()


def resolve_output_root(experiment: Experiment, base_dir: Path) -> Path:
    return _resolve_path(base_dir, experiment.output) / experiment.id


def resolve_trials_path(experiment: Experiment, base_dir: Path) -> Path:
    return resolve_output_root(experiment, base_dir) / "trials.jsonl"
