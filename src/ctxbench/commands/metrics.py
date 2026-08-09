from __future__ import annotations

from pathlib import Path
from typing import Any

from ctxbench.benchmark.selectors import RunSelector
from ctxbench.metrics.aggregate import compute_all, failure_cases
from ctxbench.metrics.io import load_inputs
from ctxbench.metrics.trial_rows import apply_selectors, build_trial_rows, parse_group_by
from ctxbench.metrics.writers import prepare_output_dir, write_outputs
from ctxbench.util.logging import PhaseLogger


def metrics_command(
    inputs: list[str],
    *,
    output: str | None = None,
    group_by: str | None = None,
    force: bool = False,
    verbose: bool = False,
    selector: RunSelector | None = None,
    evaluation_status: tuple[str, ...] = (),
    not_evaluation_status: tuple[str, ...] = (),
    command: str | None = None,
) -> int:
    logger = PhaseLogger(verbose=verbose)
    try:
        if len(inputs) > 1 and output is None:
            raise ValueError("Multiple input directories require --output for merged metrics.")
        output_dir = Path(output).expanduser() if output else Path(inputs[0]).expanduser() / "metrics"
        group_fields = parse_group_by(group_by)
        logger.info("METRICS", "metrics.inputs.discover", "Loading metrics input artifacts", inputs=len(inputs))
        artifacts = load_inputs(inputs, logger)
        rows = build_trial_rows(artifacts, logger)
        active_selector = selector or RunSelector()
        selected_rows = apply_selectors(
            rows,
            active_selector,
            evaluation_status=evaluation_status,
            not_evaluation_status=not_evaluation_status,
        )
        logger.info(
            "METRICS",
            "metrics.rows.selected",
            "Built trial metric rows",
            rows=len(rows),
            selected=len(selected_rows),
        )
        dimensions = compute_all(selected_rows, group_fields)
        failures = failure_cases(selected_rows)
        prepare_output_dir(output_dir, force=force)
        write_outputs(
            output_dir,
            group_fields=group_fields,
            trial_rows=selected_rows,
            metrics=dimensions,
            failure_rows=failures,
            inputs=artifacts,
            selectors=_selectors_manifest(active_selector, evaluation_status, not_evaluation_status),
            command=command or "llmctxbench metrics " + " ".join(inputs),
        )
        logger.info("METRICS", "metrics.completed", "Metrics completed", path=str(output_dir), rows=len(selected_rows))
        print(f"Wrote metrics to {output_dir}")
        return 0
    except Exception as exc:
        logger.error("METRICS", "metrics.failed", str(exc))
        return 1


def _selectors_manifest(
    selector: RunSelector,
    evaluation_status: tuple[str, ...],
    not_evaluation_status: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "model": list(selector.model),
        "provider": list(selector.provider),
        "instance": list(selector.instance),
        "task": list(selector.task),
        "strategy": list(selector.strategy),
        "format": list(selector.format),
        "repetition": list(selector.repetition),
        "trial": list(selector.trial_id),
        "executionStatus": list(selector.status),
        "evaluationStatus": list(evaluation_status),
        "notModel": list(selector.not_model),
        "notProvider": list(selector.not_provider),
        "notInstance": list(selector.not_instance),
        "notTask": list(selector.not_task),
        "notStrategy": list(selector.not_strategy),
        "notFormat": list(selector.not_format),
        "notRepetition": list(selector.not_repetition),
        "notExecutionStatus": list(selector.not_status),
        "notEvaluationStatus": list(not_evaluation_status),
    }

