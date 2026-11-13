from __future__ import annotations

from pathlib import Path
from typing import Any

from ctxbench.benchmark.selectors import TrialSelector
from ctxbench.metrics.aggregate import compute_all, failure_cases
from ctxbench.metrics.io import load_inputs
from ctxbench.metrics.trial_rows import apply_selectors, build_trial_rows, parse_group_by
from ctxbench.metrics.writers import prepare_output_dir, write_outputs
from ctxbench.util.logging import PhaseLogger
from ctxbench.util.fs import load_json, write_json
from ctxbench.metrics.adaptive import build_adaptive_metrics, write_adaptive_metrics


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
        if len(inputs) == 1:
            manifest_path = Path(inputs[0]).expanduser() / "manifest.json"
            if manifest_path.exists():
                manifest = load_json(manifest_path)
                if isinstance(manifest, dict) and manifest.get("workflowKind") == "adaptive":
                    from ctxbench.adaptive.artifacts import validate_workflow_manifest
                    manifest = validate_workflow_manifest(inputs[0])
                    if selector and (selector.configuration or selector.strategy or selector.representation or selector.surface or selector.repetition):
                        raise ValueError("Adaptive metrics selectors support task, instance, status, and request ID only.")
                    requests, attempts = build_adaptive_metrics(inputs[0])
                    if selector:
                        requests = [row for row in requests if
                                    (not selector.task or row.get("taskId") in selector.task) and
                                    (not selector.instance or row.get("instanceId") in selector.instance) and
                                    (not selector.status or ("delivered" if row.get("delivered") else row.get("state")) in selector.status) and
                                    (not selector.trial_id or row.get("requestId") in selector.trial_id)]
                        selected = {row["requestId"] for row in requests}
                        attempts = [row for row in attempts if row.get("requestId") in selected]
                    if output_dir.exists() and any(output_dir.iterdir()):
                        if not force:
                            raise ValueError(f"Output directory exists and is non-empty: {output_dir}. Use --force to replace it.")
                        import shutil
                        shutil.rmtree(output_dir)
                    write_adaptive_metrics(output_dir, requests, attempts)
                    request_states = {state: sum(row.get("state") == state for row in requests)
                                      for state in ("delivered", "failed", "rejected", "started")}
                    write_json(output_dir / "metrics-manifest.json", {
                        "schemaVersion": "3.0-adaptive",
                        "workflowKind": "adaptive",
                        "inputDirectory": str(Path(inputs[0]).expanduser()),
                        "requestCount": len(requests),
                        "attemptCount": len(attempts),
                        "requestStates": request_states,
                        "outputs": ["adaptive_request_metrics.csv", "adaptive_attempt_metrics.csv"],
                    })
                    print(f"Wrote adaptive metrics to {output_dir}")
                    return 0
        group_fields = parse_group_by(group_by)
        logger.info("METRICS", "metrics.inputs.discover", "Loading metrics input artifacts", inputs=len(inputs))
        artifacts = load_inputs(inputs, logger)
        rows = build_trial_rows(artifacts, logger)
        active_selector = selector or TrialSelector()
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
        if "strategy" in group_fields and "configurationId" not in group_fields:
            groups: dict[tuple[Any, ...], set[str]] = {}
            for row in selected_rows:
                groups.setdefault(tuple(row.get(field) for field in group_fields), set()).add(row["configurationId"])
            if any(len(ids) > 1 for ids in groups.values()):
                logger.warn("METRICS", "metrics.configurations.pooled", "Strategy summaries pool multiple configurations; see trial_metrics.csv and metrics-manifest.json for definitions.")
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
    selector: TrialSelector,
    evaluation_status: tuple[str, ...],
    not_evaluation_status: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "model": list(selector.model),
        "provider": list(selector.provider),
        "instance": list(selector.instance),
        "task": list(selector.task),
        "configuration": list(selector.configuration),
        "notConfiguration": list(selector.not_configuration),
        "strategy": list(selector.strategy),
        "representation": list(selector.representation),
        "repetition": list(selector.repetition),
        "trial": list(selector.trial_id),
        "executionStatus": list(selector.status),
        "evaluationStatus": list(evaluation_status),
        "notModel": list(selector.not_model),
        "notProvider": list(selector.not_provider),
        "notInstance": list(selector.not_instance),
        "notTask": list(selector.not_task),
        "notStrategy": list(selector.not_strategy),
        "notRepresentation": list(selector.not_representation),
        "notRepetition": list(selector.not_repetition),
        "notExecutionStatus": list(selector.not_status),
        "notEvaluationStatus": list(not_evaluation_status),
    }

