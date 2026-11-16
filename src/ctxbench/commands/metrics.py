from __future__ import annotations

from pathlib import Path

from ctxbench.api.workflows import registry
from ctxbench.benchmark.selectors import TrialSelector
from ctxbench.core.workflow import MetricsOptions
from ctxbench.util.logging import PhaseLogger


def metrics_command(
    inputs: list[str],
    *,
    output: str | None = None,
    group_by: str | None = None,
    force: bool = False,
    verbose: bool = False,
    selector: TrialSelector | None = None,
    evaluation_status: tuple[str, ...] = (),
    not_evaluation_status: tuple[str, ...] = (),
    command: str | None = None,
) -> int:
    logger = PhaseLogger(verbose=verbose)
    try:
        if len(inputs) > 1 and output is None:
            raise ValueError("Multiple input directories require --output for merged metrics.")
        output_dir = Path(output).expanduser() if output else Path(inputs[0]).expanduser() / "metrics"
        outcome = registry.for_inputs(inputs).write_metrics(
            inputs,
            options=MetricsOptions(
                output_dir=output_dir, group_by=group_by, force=force, selector=selector,
                evaluation_status=evaluation_status, not_evaluation_status=not_evaluation_status,
                command=command,
            ),
            logger=logger,
        )
        print(outcome.summary)
        return 0
    except Exception as exc:
        logger.error("METRICS", "metrics.failed", str(exc))
        return 1
