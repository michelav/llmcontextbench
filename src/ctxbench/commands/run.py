from __future__ import annotations

from pathlib import Path
from typing import Any

from ctxbench.ai.engine import Engine
from ctxbench.benchmark.checkpoints import (
    checkpoint_path,
    load_completed_run_ids,
    write_completed_run_ids,
)
from ctxbench.benchmark.executor import execute_runspec
from ctxbench.benchmark.models import TrialSpec
from ctxbench.benchmark.selectors import RunSelector, matches_runspec
from ctxbench.benchmark.results import (
    append_result_jsonl,
    serialize_run_result,
    write_result_file,
)
from ctxbench.util.artifacts import runresult_filename
from ctxbench.util.fs import load_json, write_json
from ctxbench.util.jsonl import append_jsonl, read_jsonl, write_jsonl
from ctxbench.util.logging import PhaseLogger, ProgressTracker


def _read_runspec_payloads(path: str) -> list[dict[str, Any]]:
    source = Path(path)
    if source.is_dir():
        return [load_json(item) for item in sorted(source.glob("*.json")) if item.name != "runs.manifest.json"]
    if source.suffix == ".jsonl":
        return [dict(item) for item in read_jsonl(source)]
    return [load_json(source)]


def _artifact_root(source: Path) -> Path:
    if source.is_dir():
        return source.parent
    if source.suffix == ".jsonl":
        return source.parent
    if source.parent.name == "runs":
        return source.parent.parent
    return source.parent


def load_runspecs(path: str) -> tuple[list[TrialSpec], str | None]:
    payloads = _read_runspec_payloads(path)
    if not payloads:
        return [], None
    if "dataset" not in payloads[0]:
        raise ValueError(
            "TrialSpec artifacts are incomplete. Re-expand the experiment to generate self-contained runspec files."
        )
    runspecs = [TrialSpec.model_validate(payload) for payload in payloads]
    experiment_path = runspecs[0].experimentPath if runspecs else None
    return runspecs, experiment_path


def _existing_run_ids_in_jsonl(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    return {
        str(item.get("trialId") or "")
        for item in read_jsonl(path)
        if isinstance(item.get("trialId"), str) and str(item.get("trialId"))
    }


def _existing_run_ids_in_result_dir(path: Path) -> set[str]:
    if not path.exists():
        return set()
    run_ids: set[str] = set()
    for item in sorted(path.glob("rr_*.json")):
        try:
            payload = load_json(item)
        except Exception:
            continue
        run_id = payload.get("trialId")
        if isinstance(run_id, str) and run_id:
            run_ids.add(run_id)
    return run_ids


def _result_path(target_dir: Path, runspec: TrialSpec) -> Path:
    return target_dir / runresult_filename(runspec.experimentId, runspec.trialId)


def _backfill_result_jsonl(
    runspecs: list[TrialSpec],
    *,
    target_dir: Path,
    target_jsonl: Path | None,
    existing_run_ids: set[str],
) -> None:
    if target_jsonl is None:
        return
    for runspec in runspecs:
        if runspec.trialId in existing_run_ids:
            continue
        result_path = _result_path(target_dir, runspec)
        if not result_path.exists():
            continue
        payload = load_json(result_path)
        _copy_trace_payload(
            payload,
            source_root=target_dir.parent,
            target_root=target_jsonl.parent,
        )
        append_jsonl(target_jsonl, [payload])
        existing_run_ids.add(runspec.trialId)


def _copy_trace_payload(payload: dict[str, Any], *, source_root: Path, target_root: Path) -> None:
    trace_ref = payload.get("traceRef")
    if not isinstance(trace_ref, str) or not trace_ref:
        return
    source_trace = source_root / trace_ref
    if not source_trace.exists():
        return
    write_json(target_root / trace_ref, load_json(source_trace))


def _rewrite_jsonl_with_run_payload(
    *,
    path: Path,
    run_id: str,
    payload: dict[str, Any],
) -> None:
    existing = []
    if path.exists():
        existing = [row for row in read_jsonl(path) if str(row.get("trialId") or "") != run_id]
    existing.append(payload)
    write_jsonl(path, existing)


def run_command(
    path: str,
    out_dir: str | None = None,
    jsonl_path: str | None = None,
    *,
    force: bool = False,
    verbose: bool = False,
    progress: bool = False,
    selector: RunSelector | None = None,
) -> int:
    source = Path(path).resolve()
    logger = PhaseLogger(verbose=verbose)
    event_logger = lambda label, message, fields: logger.phase(label, message, **fields)
    logger.phase("LOAD", "Loading run specification", path=path)
    runspecs, _experiment_path = load_runspecs(path)
    active_selector = selector or RunSelector()
    runspecs = [runspec for runspec in runspecs if matches_runspec(runspec, active_selector)]
    if not runspecs:
        print("No runspecs found.")
        return 0

    output_root = _artifact_root(source)
    artifacts = runspecs[0].artifacts
    default_dir = output_root / "results"
    target_dir = Path(out_dir).resolve() if out_dir else default_dir
    target_jsonl = (
        Path(jsonl_path).resolve()
        if jsonl_path
        else output_root / "results.jsonl"
        if artifacts.writeJsonl
        else None
    )
    write_individual_json = artifacts.writeIndividualJson
    write_traces = runspecs[0].trace.writeFiles
    file_artifact_root = target_dir.parent
    jsonl_artifact_root = target_jsonl.parent if target_jsonl is not None else None
    logger.phase("LOAD", "Run specification loading completed", runs=len(runspecs))
    logger.phase("PLAN", "Starting batch processing", input=path, discoveredRuns=len(runspecs))
    progress_tracker = ProgressTracker(total=len(runspecs), enabled=progress)
    logger.progress = progress_tracker
    progress_tracker.start()
    checkpoint_file = checkpoint_path(target_dir.parent if target_jsonl is None else target_jsonl.parent, "runs")
    experiment_id = runspecs[0].experimentId
    existing_jsonl_run_ids = _existing_run_ids_in_jsonl(target_jsonl)
    if force:
        completed_run_ids: set[str] = set()
        write_completed_run_ids(
            checkpoint_file,
            experiment_id=experiment_id,
            kind="runs",
            completed_run_ids=completed_run_ids,
        )
    else:
        completed_run_ids = load_completed_run_ids(
            checkpoint_file,
            experiment_id=experiment_id,
            kind="runs",
        )
        completed_run_ids.update(existing_jsonl_run_ids)
        if write_individual_json:
            completed_run_ids.update(_existing_run_ids_in_result_dir(target_dir))
        if completed_run_ids:
            write_completed_run_ids(
                checkpoint_file,
                experiment_id=experiment_id,
                kind="runs",
                completed_run_ids=completed_run_ids,
            )
    completed_runs = 0
    skipped_runs = 0
    engine = Engine(event_logger=event_logger)
    try:
        for runspec in runspecs:
            result_path = _result_path(target_dir, runspec)
            if runspec.trialId in completed_run_ids and not force:
                skipped_runs += 1
                logger.phase("SKIP", "Run already persisted; skipping execution", run=runspec.trialId, path=result_path)
                progress_tracker.advance()
                completed_runs += 1
                continue
            model_name = runspec.modelName or ""
            logger.phase(
                "EXECUTE",
                "Starting answer generation",
                run=runspec.trialId,
                model=model_name,
                question=runspec.taskId,
            )
            result = execute_runspec(runspec, engine)
            logger.phase(
                "EXECUTE",
                "Answer generation completed",
                run=runspec.trialId,
                model=model_name,
                question=runspec.taskId,
            )
            if write_individual_json:
                if force and result_path.exists():
                    logger.phase("WRITE", "Overwriting existing run artifact", run=result.trialId, path=result_path)
                logger.phase("WRITE", "Writing artifact", run=result.trialId, path=result_path)
                written_path = write_result_file(
                    result,
                    target_dir,
                    artifact_root=file_artifact_root,
                    write_trace=write_traces,
                )
                logger.phase("WRITE", "Artifact written", run=result.trialId, path=written_path)
            if target_jsonl is not None:
                if force:
                    _rewrite_jsonl_with_run_payload(
                        path=target_jsonl,
                        run_id=result.trialId,
                        payload=serialize_run_result(result, artifact_root=jsonl_artifact_root, write_trace=write_traces),
                    )
                else:
                    append_result_jsonl(result, target_jsonl, artifact_root=jsonl_artifact_root, write_trace=write_traces)
                completed_run_ids.add(result.trialId)
                write_completed_run_ids(
                    checkpoint_file,
                    experiment_id=experiment_id,
                    kind="runs",
                    completed_run_ids=completed_run_ids,
                )
                logger.phase("WRITE", "Artifact written", run=result.trialId, path=target_jsonl)
            else:
                completed_run_ids.add(result.trialId)
                write_completed_run_ids(
                    checkpoint_file,
                    experiment_id=experiment_id,
                    kind="runs",
                    completed_run_ids=completed_run_ids,
                )
            logger.phase("DONE", "Completed successfully", run=result.trialId)
            progress_tracker.advance()
            completed_runs += 1
    finally:
        engine.close()

    if skipped_runs and write_individual_json:
        _backfill_result_jsonl(
            runspecs,
            target_dir=target_dir,
            target_jsonl=target_jsonl,
            existing_run_ids=existing_jsonl_run_ids,
        )

    if target_jsonl is not None:
        print(
            f"Processed {completed_runs} run(s) to {target_dir} and {target_jsonl}"
            + (f" ({skipped_runs} resumed)" if skipped_runs else "")
        )
    else:
        print(
            f"Processed {completed_runs} run(s) to {target_dir}"
            + (f" ({skipped_runs} resumed)" if skipped_runs else "")
        )
    return 0
