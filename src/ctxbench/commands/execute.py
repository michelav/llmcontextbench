from __future__ import annotations

from pathlib import Path

from ctxbench.api.workflows import registry
from ctxbench.benchmark.selectors import TrialSelector
from ctxbench.core.workflow import ExecuteOptions
from ctxbench.util.logging import PhaseLogger


def execute_command(
    queries: str | None = None,
    *,
    force: bool = False,
    verbose: bool = False,
    progress: bool = False,
    selector: TrialSelector | None = None,
    retry_uncertain: bool = False,
    plugin_paths: tuple[Path, ...] = (),
) -> int:
    source = Path(queries).resolve() if queries else Path("trials.jsonl").resolve()
    logger = PhaseLogger(verbose=verbose)
    logger.info("EXECUTE", "trials.loading", "Loading trials", path=str(source))
    root = source.parent
    outcome = registry.for_run(root).execute(
        root,
        options=ExecuteOptions(
            retry_uncertain=retry_uncertain, force=force, selector=selector,
            progress=progress, plan_path=source, plugin_paths=plugin_paths,
        ),
        logger=logger,
    )
    if outcome.summary:
        print(outcome.summary)
    return 0
