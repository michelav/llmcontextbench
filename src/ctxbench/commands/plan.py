from __future__ import annotations

from pathlib import Path
import json

from ctxbench.adapters.registry import get_default_registry
from ctxbench.benchmark.experiment_loader import load_experiment
from ctxbench.benchmark.fingerprint import digest, file_digest, implementation_digest, tree_digest
from ctxbench.benchmark.models import DatasetProvenance
from ctxbench.benchmark.provisioning import PROVISIONING_ARTIFACT_VERSION, validate_artifact_directory
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
from ctxbench.util.logging import PhaseLogger, ProgressTracker, dataset_log_context, trial_log_context


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
    source_path = Path(path).resolve()
    with source_path.open(encoding="utf-8") as stream:
        definition_header = json.load(stream)
    if isinstance(definition_header, dict) and definition_header.get("workflowKind") == "adaptive":
        from ctxbench.adaptive.artifacts import validate_adaptive_definition, write_adaptive_artifacts
        target = Path(output).resolve() if output else source_path.parent / str(definition_header.get("output", "outputs"))
        plan = validate_adaptive_definition(definition_header)
        dataset_metadata = definition_header.get("dataset")
        evaluation = definition_header.get("evaluation")
        trace = definition_header.get("trace")
        if target.exists() and any(target.iterdir()):
            raise ValueError("Adaptive planning requires a fresh output directory; existing plans are never migrated.")
        dataset = dataset_metadata if isinstance(dataset_metadata, dict) else {
            "id": plan.dataset_id or "unknown", "version": plan.dataset_version or "unknown",
            "origin": None, "materializedPath": None,
        }
        if ((plan.dataset_id and dataset.get("id") != plan.dataset_id)
                or (plan.dataset_version and dataset.get("version") != plan.dataset_version)):
            raise ValueError("Adaptive definition dataset differs from its frozen plan provenance.")
        write_adaptive_artifacts(target, plan, dataset=dataset, evaluation=evaluation, trace=trace)
        print(f"Planned {len(plan.requests)} adaptive request(s) → {target / 'adaptive-plan.json'}")
        return 0
    logger.info("PLAN", "experiment.loaded", "Loading experiment", path=path)
    experiment = load_experiment(path)
    if experiment.experimentKind == "adaptive":
        raise ValueError(
            "Legacy kind=adaptive definitions are not planned. Provide a fresh workflowKind=adaptive "
            "definition with adaptive plan schemaVersion 2."
        )
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
    dataset_provenance = _dataset_provenance(adapter)
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
        "provisioningArtifactVersion": 2,
        "configurations": {key: experiment.configurations[key].model_dump(mode="json") for key in experiment.factors["configuration"]},
        "surfaces": {key: value.model_dump(mode="json") for key, value in experiment.surfaces.items()},
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
    if experiment.definitionVersion == 3:
        manifest["schemaVersion"] = 3
        manifest["provisioningArtifactVersion"] = PROVISIONING_ARTIFACT_VERSION
        manifest["executionRecordVersion"] = 1
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

    print(f"Planned {len(runspecs)} trials → {trials_path}")
    return 0
