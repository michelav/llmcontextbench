from __future__ import annotations

from pathlib import Path
import json

from ctxbench.api.workflows import registry
from ctxbench.util.logging import PhaseLogger


def plan_command(
    path: str,
    output: str | None = None,
    *,
    verbose: bool = False,
    progress: bool = False,
    cache_dir: Path | None = None,
) -> int:
    logger = PhaseLogger(verbose=verbose)
    source_path = Path(path).resolve()
    with source_path.open(encoding="utf-8") as stream:
        definition_header = json.load(stream)
    workflow = registry.for_definition(definition_header)
    definition = workflow.load_definition(path, logger=logger)
    outcome = workflow.plan(
        definition,
        output=Path(output) if output else None,
        cache_dir=cache_dir,
        logger=logger,
        progress=progress,
    )
    print(outcome.summary)
    return 0
