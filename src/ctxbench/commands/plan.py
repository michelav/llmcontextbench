from __future__ import annotations

from pathlib import Path

from ctxbench.adapters.registry import get_default_registry
from ctxbench.benchmark.experiment_loader import load_experiment
from ctxbench.benchmark.models import DatasetProvenance
from ctxbench.benchmark.paths import resolve_output_root, resolve_trials_path
from ctxbench.benchmark.runspec_generator import generate_runspecs
from ctxbench.dataset.cache import DatasetCache
from ctxbench.dataset.conflicts import AmbiguousDatasetError
from ctxbench.dataset.errors import AdapterUnavailableError
from ctxbench.dataset.package import DatasetPackage
from ctxbench.dataset.resolver import DatasetNotFoundError, DatasetResolver, MultiDatasetError
from ctxbench.dataset.validation import validate_package
from ctxbench.util.fs import ensure_dir, write_json
from ctxbench.util.jsonl import write_jsonl
from ctxbench.util.logging import PhaseLogger, ProgressTracker


def _dataset_provenance(package: DatasetPackage) -> DatasetProvenance:
    capability_report = package.capability_report()
    return DatasetProvenance(
        id=package.identity(),
        version=package.version(),
        origin=package.origin(),
        resolved_revision=capability_report.resolved_revision,
        content_hash=capability_report.content_hash,
        materialized_path=capability_report.materialized_path,
    )


def plan_command(
    path: str,
    output: str | None = None,
    *,
    verbose: bool = False,
    progress: bool = False,
    cache_dir: Path | None = None,
) -> int:
    logger = PhaseLogger(verbose=verbose)
    logger.phase("LOAD", "Loading experiment", path=path)
    experiment = load_experiment(path)
    base_dir = Path(path).resolve().parent
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
    logger.phase(
        "LOAD",
        "Dataset resolved",
        dataset=adapter_metadata.name,
        version=capability_report.version,
        questions=len(adapter.list_task_ids()),
        instances=len(adapter.list_instance_ids()),
    )
    logger.phase(
        "LOAD",
        "Dataset capability check",
        conformant=capability_report.conformant,
        missingMandatory=len(capability_report.missing_mandatory),
        nonconformantDescriptors=len(capability_report.nonconformant_descriptors),
    )
    dataset_provenance = _dataset_provenance(adapter)
    runspecs = generate_runspecs(
        experiment,
        base_dir,
        adapter,
        dataset_provenance,
        experiment_path=path,
        on_warning=lambda message, **fields: logger.warn(message, **fields),
    )
    logger.phase("PLAN", "Expanding trials", input=path, total=len(runspecs))

    output_root = Path(output).resolve() if output else resolve_output_root(experiment, base_dir)
    trials_path = resolve_trials_path(experiment, base_dir) if not output else output_root / "trials.jsonl"
    manifest_path = output_root / "manifest.json"

    ensure_dir(output_root)

    progress_tracker = ProgressTracker(total=len(runspecs), enabled=progress)
    logger.progress = progress_tracker
    progress_tracker.start()

    payloads = []
    for runspec in runspecs:
        payloads.append(runspec.to_persisted_artifact())
        logger.phase("PLAN", "Trial prepared", run=runspec.trialId)
        progress_tracker.advance()

    write_jsonl(trials_path, payloads)
    logger.phase("WRITE", "Trials written", path=str(trials_path), total=len(payloads))

    manifest = {
        "experimentId": experiment.id,
        "experimentPath": str(Path(path).resolve()),
        "dataset": dataset_provenance.model_dump(mode="json"),
        "evaluation": {
            "enabled": experiment.evaluation.enabled,
            "judges": [item.model_dump(mode="json") for item in experiment.evaluation.judges],
        },
        "trace": experiment.trace.model_dump(mode="json"),
        "artifacts": experiment.artifacts.model_dump(mode="json"),
    }
    write_json(manifest_path, manifest)
    logger.phase("WRITE", "Manifest written", path=str(manifest_path))

    print(f"Planned {len(runspecs)} trials → {trials_path}")
    return 0
