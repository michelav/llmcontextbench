from __future__ import annotations

from pathlib import Path

from ctxbench.benchmark.experiment_loader import load_experiment
from ctxbench.benchmark.paths import resolve_expand_jsonl_path, resolve_expand_output_dir
from ctxbench.benchmark.runspec_generator import generate_runspecs
from ctxbench.dataset.provider import DatasetProvider
from ctxbench.util.artifacts import runspec_filename
from ctxbench.util.fs import ensure_dir, write_json
from ctxbench.util.jsonl import write_jsonl
from ctxbench.util.logging import PhaseLogger, ProgressTracker


def _runs_manifest_targets(target_dir: Path, target_jsonl: Path | None) -> list[Path]:
    candidates = {target_dir / "runs.manifest.json"}
    if target_jsonl is not None:
        candidates.add(target_jsonl.parent / "runs.manifest.json")
    return sorted(candidates)


def _evaluation_manifest_targets(target_dir: Path, target_jsonl: Path | None) -> list[Path]:
    candidates = {target_dir.parent / "evaluation.manifest.json"}
    if target_jsonl is not None:
        candidates.add(target_jsonl.parent / "evaluation.manifest.json")
    return sorted(candidates)


def validate_experiment(path: str) -> int:
    load_experiment(path)
    print(f"{path}: valid experiment")
    return 0


def expand_experiment(
    path: str,
    out_dir: str | None = None,
    jsonl_path: str | None = None,
    *,
    verbose: bool = False,
    progress: bool = False,
) -> int:
    progress_tracker = ProgressTracker(total=0, enabled=False)
    logger = PhaseLogger(verbose=verbose, progress=progress_tracker)
    logger.phase("LOAD", "Loading experiment", path=path)
    experiment = load_experiment(path)
    base_dir = Path(path).resolve().parent
    provider = DatasetProvider.from_experiment(experiment, base_dir)
    logger.phase(
        "LOAD",
        "Dataset loading completed",
        questions=len(provider.list_question_ids()),
        instances=len(provider.list_instance_ids()),
    )
    runspecs = generate_runspecs(
        experiment,
        base_dir,
        experiment_path=path,
        on_warning=lambda message, **fields: logger.warn(message, **fields),
    )
    logger.phase("PLAN", "Starting batch processing", input=path, discoveredRuns=len(runspecs))
    payloads = [runspec.to_persisted_artifact() for runspec in runspecs]
    default_dir = resolve_expand_output_dir(experiment, base_dir)
    target_dir = Path(out_dir).resolve() if out_dir else default_dir
    target_jsonl = (
        Path(jsonl_path).resolve()
        if jsonl_path
        else resolve_expand_jsonl_path(experiment, base_dir)
        if experiment.artifacts.writeJsonl
        else None
    )
    ensure_dir(target_dir)
    progress_tracker = ProgressTracker(total=len(runspecs), enabled=progress)
    logger.progress = progress_tracker
    progress_tracker.start()

    if experiment.artifacts.writeIndividualJson:
        for runspec in runspecs:
            artifact_path = target_dir / runspec_filename(runspec.experimentId, runspec.trialId)
            logger.phase("WRITE", "Writing artifact", run=runspec.trialId, path=artifact_path)
            write_json(artifact_path, runspec.to_persisted_artifact())
            logger.phase("WRITE", "Artifact written", run=runspec.trialId, path=artifact_path)
            logger.phase("DONE", "Completed successfully", run=runspec.trialId)
            progress_tracker.advance()
    else:
        for runspec in runspecs:
            logger.phase("DONE", "TrialSpec prepared", run=runspec.trialId)
            progress_tracker.advance()

    if target_jsonl is not None:
        write_jsonl(target_jsonl, payloads)
    runs_manifest_payload = {
        "experimentId": experiment.id,
        "experimentPath": str(Path(path).resolve()),
        "artifacts": experiment.artifacts.model_dump(mode="json"),
        "trace": experiment.trace.model_dump(mode="json"),
    }
    evaluation_manifest_payload = {
        "experimentId": experiment.id,
        "evaluation": {
            "enabled": experiment.evaluation.enabled,
            "output": experiment.evaluation.output or "evaluation",
            "jsonl": experiment.evaluation.jsonl or "evaluation.jsonl",
            "artifacts": experiment.artifacts.model_dump(mode="json"),
            "trace": experiment.trace.model_dump(mode="json"),
            "judges": [
                item.model_dump(mode="json")
                for item in experiment.evaluation.judges
            ],
        },
    }
    for manifest_path in _runs_manifest_targets(target_dir, target_jsonl):
        write_json(manifest_path, runs_manifest_payload)
        logger.phase("WRITE", "Artifact written", path=manifest_path)
    for manifest_path in _evaluation_manifest_targets(target_dir, target_jsonl):
        write_json(manifest_path, evaluation_manifest_payload)
        logger.phase("WRITE", "Artifact written", path=manifest_path)

    if target_jsonl is not None:
        print(f"Wrote {len(runspecs)} runspec(s) to {target_dir} and {target_jsonl}")
    else:
        print(f"Wrote {len(runspecs)} runspec(s) to {target_dir}")
    return 0
