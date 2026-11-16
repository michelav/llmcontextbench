"""Static benchmark workflow over the shared execution service."""
from __future__ import annotations

from pathlib import Path
from time import perf_counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ctxbench.ai.engine import Engine
from ctxbench.ai.models.base import AIResult
from ctxbench.benchmark.execution_records import rebuild_responses
from ctxbench.benchmark.executor import execute_runtime_request, resolve_trial_dataset
from ctxbench.benchmark.models import TrialSpec
from ctxbench.benchmark.provisioning import validate_manifest
from ctxbench.benchmark.results import serialize_run_result
from ctxbench.benchmark.runtime_adapter import TrialRuntimeAdapter
from ctxbench.execution.service import ExecutionRequest, ExecutionSession, TrialExecutionService
from ctxbench.runtime.models import ExecutionResult
from ctxbench.util.clock import utc_now_iso
from ctxbench.util.logging import PhaseLogger, ProgressTracker, trial_log_context
from ctxbench.core.workflow import (
    ExecuteOptions, ExecuteOutcome, MetricsOptions, MetricsOutcome, PlanOutcome, RunStatus,
    StatusGroupingError,
)


@dataclass(frozen=True, slots=True)
class BenchmarkDefinition:
    """A validated benchmark definition plus the location that relative paths resolve against."""
    experiment: Any
    base_dir: Path
    source: str | None = None   # definition path as given by the caller; None for in-memory input


class BenchmarkWorkflow:
    """Static benchmark workflow: plan a trial matrix, execute it, report on it."""

    kind = "benchmark"

    # ---- definition and planning -------------------------------------------------------

    def load_definition(self, source, *, logger: PhaseLogger | None = None) -> BenchmarkDefinition:
        from ctxbench._compat import ValidationError
        from ctxbench.benchmark.definitions import planner_payload
        from ctxbench.benchmark.experiment_loader import load_experiment
        from ctxbench.benchmark.models import Experiment

        if isinstance(source, Mapping):
            payload = _copy_json(source)
            if payload.get("extends") is not None:
                raise ValueError("An in-memory definition cannot use 'extends'; pass a definition path.")
            base_dir = Path.cwd().resolve()
            dataset = payload.get("dataset")
            if isinstance(dataset, dict) and isinstance(dataset.get("root"), str):
                dataset["root"] = str((base_dir / Path(dataset["root"]).expanduser()).resolve())
            elif isinstance(dataset, str):
                payload["dataset"] = str((base_dir / Path(dataset).expanduser()).resolve())
            try:
                experiment = Experiment.model_validate(planner_payload(payload))
                validator = getattr(experiment, "_validate_model", None)
                if validator:
                    validator()
            except (ValidationError, ValueError) as exc:
                raise ValueError(f"Invalid experiment: {exc}") from exc
            return BenchmarkDefinition(experiment, base_dir, None)
        if logger is not None:
            logger.info("PLAN", "experiment.loaded", "Loading experiment", path=source)
        return BenchmarkDefinition(load_experiment(source), Path(source).resolve().parent, str(source))

    def plan(self, definition: BenchmarkDefinition, *, output: Path | None, cache_dir: Path | None = None,
             plugin_paths: Sequence[Path] = (), logger: PhaseLogger | None = None,
             progress: bool = False) -> PlanOutcome:
        from ctxbench.adapters.registry import get_default_registry
        from ctxbench.benchmark.fingerprint import digest, file_digest, implementation_digest, tree_digest
        from ctxbench.benchmark.models import DatasetProvenance
        from ctxbench.benchmark.paths import resolve_output_root, resolve_trials_path
        from ctxbench.benchmark.provisioning import PROVISIONING_ARTIFACT_VERSION, validate_artifact_directory
        from ctxbench.benchmark.runspec_generator import generate_runspecs
        from ctxbench.dataset.cache import DatasetCache
        from ctxbench.dataset.conflicts import AmbiguousDatasetError
        from ctxbench.dataset.errors import AdapterUnavailableError
        from ctxbench.dataset.resolver import DatasetNotFoundError, DatasetResolver, MultiDatasetError
        from ctxbench.dataset.validation import validate_package
        from ctxbench.util.fs import ensure_dir, write_json
        from ctxbench.util.jsonl import write_jsonl
        from ctxbench.util.logging import dataset_log_context

        logger = logger or PhaseLogger()
        experiment = definition.experiment
        base_dir = definition.base_dir
        path = definition.source
        cache = DatasetCache(cache_dir=cache_dir)
        resolver = DatasetResolver()
        try:
            resolved = resolver.resolve_for_planning(experiment.dataset, cache)
        except DatasetNotFoundError as exc:
            raise DatasetNotFoundError(str(exc)) from exc
        except AmbiguousDatasetError as exc:
            raise AmbiguousDatasetError(str(exc)) from exc
        except MultiDatasetError as exc:
            raise MultiDatasetError(
                "Experiment references to multiple datasets are not supported."
            ) from exc
        try:
            adapter = get_default_registry().resolve(resolved.adapter_ref)
        except AdapterUnavailableError:
            adapter = resolved.package
        adapter_metadata = adapter.metadata()
        capability_report = validate_package(adapter)
        report = adapter.capability_report()
        dataset_provenance = DatasetProvenance(
            id=adapter.identity(),
            version=adapter.version(),
            origin=adapter.origin(),
            resolved_revision=report.resolved_revision,
            content_hash=report.content_hash,
            materialized_path=report.materialized_path,
        )
        logger.info(
            "PLAN",
            "dataset.resolved",
            "Dataset resolved",
            **dataset_log_context(dataset_provenance, dataset_name=adapter_metadata.name),
            tasks=len(adapter.list_task_ids()),
            instances=len(adapter.list_instance_ids()),
        )
        logger.info(
            "PLAN",
            "dataset.capability.checked",
            "Dataset capability check",
            **dataset_log_context(dataset_provenance, dataset_name=adapter_metadata.name),
            conformant=capability_report.conformant,
            missingMandatory=len(capability_report.missing_mandatory),
            nonconformantDescriptors=len(capability_report.nonconformant_descriptors),
        )
        runspecs = generate_runspecs(
            experiment,
            base_dir,
            adapter,
            dataset_provenance,
            experiment_path=path,
            on_warning=lambda message, **fields: logger.warn("PLAN", "trial.prepare.warning", message, **fields),
        )
        logger.info("PLAN", "trials.expanded", "Expanding trials", input=path, total=len(runspecs))

        output_root = Path(output).resolve() if output else resolve_output_root(experiment, base_dir)
        trials_path = resolve_trials_path(experiment, base_dir) if not output else output_root / "trials.jsonl"
        manifest_path = output_root / "manifest.json"

        if output_root.exists() and any(output_root.iterdir()):
            validate_artifact_directory(output_root)
            raise ValueError("Planning requires a fresh output directory to preserve existing trial snapshots.")
        if trials_path.exists():
            raise ValueError("Planning requires a fresh trials path.")
        ensure_dir(output_root)

        progress_tracker = ProgressTracker(total=len(runspecs), enabled=progress)
        logger.progress = progress_tracker
        progress_tracker.start()

        payloads = []
        for runspec in runspecs:
            payloads.append(runspec.to_persisted_artifact())
            logger.info("PLAN", "trial.prepared", "Trial prepared", **trial_log_context(runspec))
            progress_tracker.advance()

        write_jsonl(trials_path, payloads)
        logger.info("PLAN", "trials.written", "Trials written", path=str(trials_path), total=len(payloads))

        manifest = {
            "schemaVersion": 3,
            "provisioningArtifactVersion": PROVISIONING_ARTIFACT_VERSION,
            "executionRecordVersion": 1,
            "configurations": {key: experiment.configurations[key].model_dump(mode="json") for key in experiment.factors["configuration"]},
            "surfaces": {key: value.model_dump(mode="json") for key, value in experiment.surfaces.items()},
            "experimentId": experiment.id,
            "experimentPath": str(Path(path).resolve()) if path else None,
            "dataset": dataset_provenance.model_dump(mode="json"),
            "evaluation": {
                "enabled": experiment.evaluation.enabled,
                "judges": [item.model_dump(mode="json") for item in experiment.evaluation.judges],
            },
            "trace": experiment.trace.model_dump(mode="json"),
            "artifacts": experiment.artifacts.model_dump(mode="json"),
        }
        write_json(output_root / "resolved.json", experiment.resolvedDefinition)
        dataset_root = dataset_provenance.materialized_path
        inputs = {
            "artifacts": {name: file_digest(output_root / name) for name in ("resolved.json", "trials.jsonl")},
            "implementation": implementation_digest(),
            "dataset": tree_digest(Path(dataset_root)) if dataset_root else dataset_provenance.content_hash,
        }
        manifest["fingerprintInputs"] = inputs
        manifest["executionFingerprint"] = digest(inputs)
        write_json(manifest_path, manifest)
        logger.info("PLAN", "manifest.written", "Manifest written", path=str(manifest_path))
        return PlanOutcome(experiment.id, self.kind, output_root, trials_path, len(runspecs),
                           f"Planned {len(runspecs)} trials → {trials_path}")

    # ---- execution ---------------------------------------------------------------------

    def execute(self, root: Path, *, options: ExecuteOptions, logger: PhaseLogger | None = None) -> ExecuteOutcome:
        from ctxbench.benchmark.execution_records import execution_lock
        from ctxbench.benchmark.fingerprint import verify_snapshot
        from ctxbench.benchmark.provisioning import validate_artifact_directory
        from ctxbench.benchmark.selectors import TrialSelector, matches_trial_spec

        logger = logger or PhaseLogger()
        root = Path(root)
        source = options.plan_path or root / "trials.jsonl"
        manifest = validate_manifest(root)
        workflow_id = str(manifest.get("experimentId", "unknown"))
        with execution_lock(root):
            verify_snapshot(root, manifest, execution=True)
            rebuild_responses(root, execution_fingerprint=str(manifest["executionFingerprint"]))
            validate_artifact_directory(root)
            runspecs = _load_runspecs(source)
            active_selector = options.selector or TrialSelector()
            runspecs = [r for r in runspecs if matches_trial_spec(r, active_selector)]
            if not runspecs:
                return ExecuteOutcome(workflow_id, self.kind, {"processed": 0, "skipped": 0},
                                      "No trials matched the selector.")
            processed, skipped = execute_benchmark_trials(
                runspecs,
                artifact_root=root,
                manifest=manifest,
                force=options.force,
                retry_uncertain=options.retry_uncertain,
                logger=logger,
                progress=options.progress,
            )
        return ExecuteOutcome(
            workflow_id, self.kind, {"processed": processed, "skipped": skipped},
            f"Processed {processed} trial(s) → {root / 'responses.jsonl'}"
            + (f" ({skipped} skipped)" if skipped else ""),
        )

    # ---- responses, status, metrics ----------------------------------------------------

    def prepare_responses(self, root: Path) -> Mapping[str, Any]:
        """Validate the run and refresh its response projection; returns the manifest."""
        from ctxbench.benchmark.provisioning import validate_artifact_directory
        manifest = validate_manifest(Path(root))
        rebuild_responses(root, execution_fingerprint=str(manifest["executionFingerprint"]))
        validate_artifact_directory(root)
        return manifest

    def responses(self, root: Path):
        from ctxbench.util.jsonl import read_jsonl
        yield from read_jsonl(Path(root) / "responses.jsonl")

    def trials(self, root: Path):
        from ctxbench.util.jsonl import read_jsonl
        yield from read_jsonl(Path(root) / "trials.jsonl")

    def status(self, root: Path, *, by: str | None = None) -> RunStatus:
        from ctxbench.benchmark.execution_records import latest_attempt_states
        from ctxbench.benchmark.provisioning import validate_artifact_directory
        from ctxbench.util.jsonl import read_jsonl
        from ctxbench.util.status_tables import judge_breakdown_lines, last_status_map, tally, trial_id

        root = Path(root)
        manifest = validate_manifest(root)
        rebuild_responses(root, execution_fingerprint=str(manifest["executionFingerprint"]))
        attempt_states = latest_attempt_states(root)
        validate_artifact_directory(root)
        trials_path = root / "trials.jsonl"

        experiment_id = str(manifest.get("experimentId", "unknown"))
        trial_count = sum(1 for _ in read_jsonl(trials_path)) if trials_path.exists() else 0
        response_map = last_status_map(root / "responses.jsonl")
        response_tally = tally(response_map)
        eval_tally = tally(last_status_map(root / "evals.jsonl"))

        response_success = response_tally.get("success", 0)
        response_error = response_tally.get("error", 0)
        response_total = sum(response_tally.values())
        eval_done = eval_tally.get("evaluated", 0)
        eval_error = eval_tally.get("error", 0)
        eval_total = sum(eval_tally.values())
        uncertain_count = sum(state == "started" for state in attempt_states.values())
        execute_pending = max(0, trial_count - response_total - uncertain_count)
        eval_pending = max(0, response_success - eval_total)

        col = (10, 8, 10, 8, 8, 8)
        header = (
            f"{'Phase':<{col[0]}} {'Total':>{col[1]}} {'Success':>{col[2]}} "
            f"{'Failed':>{col[3]}} {'Started':>{col[4]}} {'Pending':>{col[5]}}"
        )
        lines = [
            f"Experiment : {experiment_id}",
            f"Directory  : {root}",
            "",
            header,
            "─" * len(header),
            f"{'execute':<{col[0]}} {trial_count:>{col[1]}} {response_success:>{col[2]}} "
            f"{response_error:>{col[3]}} {uncertain_count:>{col[4]}} {execute_pending:>{col[5]}}",
            f"{'eval':<{col[0]}} {response_success:>{col[1]}} {eval_done:>{col[2]}} "
            f"{eval_error:>{col[3]}} {0:>{col[4]}} {eval_pending:>{col[5]}}",
        ]
        if by:
            if by == "judge":
                lines.extend(judge_breakdown_lines(root, response_success))
            elif by in {"configuration", "representation", "surface", "strategy", "model", "instance", "task"}:
                field_name = {"configuration": "configurationId", "model": "modelId",
                              "instance": "instanceId", "task": "taskId"}.get(by, by)
                groups: dict[str, list[dict[str, object]]] = {}
                for trial in read_jsonl(trials_path):
                    groups.setdefault(str(trial.get(field_name)), []).append(trial)
                lines.append(f"\n{by:<24} {'Total':>8} {'Success':>8} {'Failed':>8} {'Pending':>8}")
                for label, trials in sorted(groups.items()):
                    statuses = [response_map.get(trial_id(trial)) for trial in trials]
                    success = statuses.count("success")
                    failed = statuses.count("error")
                    lines.append(f"{label:<24} {len(trials):>8} {success:>8} {failed:>8} {statuses.count(None):>8}")
                    if by == "strategy" and len({t["configurationId"] for t in trials}) > 1:
                        lines.append("  Pools multiple configurations: "
                                     + ", ".join(sorted({str(t["configurationId"]) for t in trials})))
            else:
                raise StatusGroupingError(f"Unsupported status grouping: {by}", lines)
        counts = {
            "planned": trial_count, "succeeded": response_success, "failed": response_error,
            "started": uncertain_count, "pending": execute_pending,
            "evaluated": eval_done, "evaluationFailed": eval_error, "evaluationPending": eval_pending,
        }
        return RunStatus(experiment_id, self.kind, root, counts, tuple(lines))

    def metric_tables(self, root: Path):
        from ctxbench.metrics.io import load_inputs
        from ctxbench.metrics.trial_rows import build_trial_rows
        logger = PhaseLogger()
        return {"trials": build_trial_rows(load_inputs([str(root)], logger), logger)}

    def write_metrics(self, roots: Sequence[str], *, options: MetricsOptions,
                      logger: PhaseLogger | None = None) -> MetricsOutcome:
        from ctxbench.benchmark.selectors import TrialSelector
        from ctxbench.metrics.aggregate import compute_all, failure_cases
        from ctxbench.metrics.io import load_inputs
        from ctxbench.metrics.trial_rows import apply_selectors, build_trial_rows, parse_group_by
        from ctxbench.metrics.writers import prepare_output_dir, write_outputs

        logger = logger or PhaseLogger()
        inputs = list(roots)
        output_dir = options.output_dir
        group_fields = parse_group_by(options.group_by)
        logger.info("METRICS", "metrics.inputs.discover", "Loading metrics input artifacts", inputs=len(inputs))
        artifacts = load_inputs(inputs, logger)
        rows = build_trial_rows(artifacts, logger)
        active_selector = options.selector or TrialSelector()
        selected_rows = apply_selectors(
            rows,
            active_selector,
            evaluation_status=options.evaluation_status,
            not_evaluation_status=options.not_evaluation_status,
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
        prepare_output_dir(output_dir, force=options.force)
        write_outputs(
            output_dir,
            group_fields=group_fields,
            trial_rows=selected_rows,
            metrics=dimensions,
            failure_rows=failures,
            inputs=artifacts,
            selectors=_selectors_manifest(active_selector, options.evaluation_status, options.not_evaluation_status),
            command=options.command or "llmctxbench metrics " + " ".join(inputs),
        )
        logger.info("METRICS", "metrics.completed", "Metrics completed", path=str(output_dir), rows=len(selected_rows))
        return MetricsOutcome(self.kind, output_dir, {"rows": len(selected_rows)}, f"Wrote metrics to {output_dir}")


def _copy_json(value: Mapping[str, Any]) -> dict[str, Any]:
    from copy import deepcopy
    return deepcopy(dict(value))


def _load_runspecs(path: Path) -> list[TrialSpec]:
    from ctxbench.util.jsonl import read_jsonl
    if not path.exists():
        raise FileNotFoundError(f"Trials file not found: {path}. Run 'llmctxbench plan' first.")
    payloads = [dict(item) for item in read_jsonl(path)]
    if not payloads:
        return []
    if "dataset" not in payloads[0]:
        raise ValueError(
            "Trials file is missing context data. Re-run 'llmctxbench plan' to regenerate."
        )
    return [TrialSpec.model_validate(payload) for payload in payloads]


def _selectors_manifest(selector, evaluation_status: tuple[str, ...],
                        not_evaluation_status: tuple[str, ...]) -> dict[str, Any]:
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


def execute_benchmark_trials(
    runspecs: list[TrialSpec],
    *,
    artifact_root: Path,
    manifest: dict[str, Any],
    force: bool,
    retry_uncertain: bool,
    logger: PhaseLogger,
    progress: bool,
    local_mcp_runtime_decorator=None,
) -> tuple[int, int]:
    """Execute a frozen benchmark trial selection and rebuild its response projection.

    Returns ``(processed, skipped)``.
    """
    validate_manifest(artifact_root)
    service = TrialExecutionService(artifact_root)
    latest_by_trial = {
        runspec.trialId: _latest_attempt(service.attempts(runspec.trialId))
        for runspec in runspecs
    }
    expected_fingerprint = str(manifest["executionFingerprint"])
    for trial_id, latest in latest_by_trial.items():
        if latest and latest.get("executionFingerprint") != expected_fingerprint:
            raise ValueError(f"Execution fingerprint mismatch in attempt record for trialId {trial_id}.")
    uncertain = [trial_id for trial_id, record in latest_by_trial.items() if record and record["state"] == "started"]
    if uncertain and not retry_uncertain:
        ids = ", ".join(uncertain[:5])
        suffix = "…" if len(uncertain) > 5 else ""
        raise ValueError(
            f"Execution has uncertain started attempts for trialId(s): {ids}{suffix}. "
            "Inspect execution-records; pass --retry-uncertain to create new attempts."
        )

    progress_tracker = ProgressTracker(total=len(runspecs), enabled=progress)
    logger.progress = progress_tracker
    progress_tracker.start()
    session = ExecutionSession(Engine(event_logger=_event_logger(logger)))
    processed = skipped = 0
    try:
        for runspec in runspecs:
            latest = latest_by_trial[runspec.trialId]
            if latest and latest["state"] in {"succeeded", "failed"} and not force:
                skipped += 1
                processed += 1
                progress_tracker.advance()
                logger.info(
                    "EXECUTE", "trial.response.skipped", "Attempt already completed; skipping",
                    **trial_log_context(runspec), status=latest["result"]["status"],
                )
                continue

            runtime_adapter = TrialRuntimeAdapter()
            dataset = resolve_trial_dataset(runspec)
            request = ExecutionRequest(
                execution_id=runspec.trialId,
                workflow_id=runspec.experimentId,
                correlation_id=runspec.trialId,
                experiment_id=runspec.experimentId,
                execution_fingerprint=expected_fingerprint,
                task_id=runspec.taskId,
                instance_id=runspec.instanceId,
                candidate_id=runspec.configurationId,
                payload=runtime_adapter.to_runtime_request(runspec),
                trial_id=runspec.trialId,
            )

            def invoke(_request, active_session):
                started_at = utc_now_iso()
                started_clock = perf_counter()
                try:
                    execution = execute_runtime_request(
                        _request.payload, active_session.resource, dataset,
                        local_mcp_runtime_decorator=local_mcp_runtime_decorator,
                    )
                    result = runtime_adapter.to_trial_result(runspec, execution)
                except Exception as exc:
                    result = TrialRuntimeAdapter().to_trial_result(
                        runspec,
                        ExecutionResult(
                            ai_result=AIResult(answer="", error=str(exc)),
                            started_at=started_at,
                            finished_at=utc_now_iso(),
                            duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
                        ),
                    )
                return serialize_run_result(
                    result,
                    artifact_root=artifact_root,
                    write_trace=runspec.trace.writeFiles,
                )

            outcome = service.execute(
                request, session, invoke, force=force,
                retry_uncertain=retry_uncertain,
            )
            logger.info(
                "EXECUTE", "trial.response.completed", "Response generated",
                **trial_log_context(runspec), status=outcome.result.get("status"),
                attemptId=outcome.attempt_id,
            )
            progress_tracker.advance()
            processed += 1
    finally:
        session.close()

    rebuild_responses(artifact_root, execution_fingerprint=expected_fingerprint)
    return processed, skipped


def _latest_attempt(attempts: list[dict[str, Any]]) -> dict[str, Any] | None:
    return attempts[-1] if attempts else None


def _event_logger(logger: PhaseLogger):
    def emit(event_name: str, message: str, fields: dict[str, object]) -> None:
        payload = dict(fields)
        level = str(payload.pop("level", "INFO"))
        phase = str(payload.pop("phase", "EXECUTE"))
        logger.event(level, phase, event_name, message, **payload)
    return emit
