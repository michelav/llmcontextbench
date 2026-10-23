from __future__ import annotations

from pathlib import Path

from ctxbench._compat import ValidationError
from ctxbench.benchmark.models import Experiment
from ctxbench.benchmark.definitions import planner_payload, resolve_definition


def load_experiment(path: str | Path) -> Experiment:
    try:
        experiment = Experiment.model_validate(planner_payload(resolve_definition(path)))
        validator = getattr(experiment, "_validate_model", None)
        if validator:
            validator()
        return experiment
    except (ValidationError, ValueError) as exc:
        raise ValueError(f"Invalid experiment at {path}: {exc}") from exc
