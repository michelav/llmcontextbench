from __future__ import annotations

import json
from pathlib import Path
from typing import override

from ctxbench.benchmark.models import ExperimentDataset
from ctxbench.benchmark.surfaces import ResolvedSurface, SurfaceSpec
from ctxbench.dataset.capabilities import DatasetCapabilityReport, SignalCapability, SignalCost
from ctxbench.dataset.errors import UnsupportedRepresentationError
from ctxbench.dataset.package import DatasetMetadata
from ctxbench.dataset.payloads import ContextPayload, EvidencePayload, TaskPayload
from ctxbench.dataset.provider import LocalDatasetPackage
from ctxbench.dataset.validation import validate_package
from ctxbench.adapters.repoqa.mcp_server import build_repoqa_mcp_server
from ctxbench.adapters.repoqa.tools import REPOQA_ALL_OPERATIONS, RepoQAToolService
from ctxbench.adaptive.sensors import AssessmentInput, QualityObservation, SensorClass, SensorCost
from ctxbench.core.provenance import Provenance, TokenUsage
from ctxbench.util.fs import load_json


REPRESENTATION_ARTIFACTS = {
    "code": "code_context.txt",
    "code_context": "code_context.txt",
    "text": "code_context.txt",
    "json": "parsed.json",
    "parsed": "parsed.json",
    "parsed_json": "parsed.json",
    "blocks": "blocks.json",
    "oracle": "oracle.json"
}


class _RepoQAOnlineAssessor:
    """Reference-data scorer exposed as an explicit privileged online signal."""

    def __init__(self, dataset_root: str | Path, capability: SignalCapability) -> None:
        self.dataset_root = Path(dataset_root)
        self.capability = capability

    def assess(self, item: AssessmentInput) -> QualityObservation:
        from ctxbench.adapters.repoqa.evaluation import (
            _load_native_task, _load_raw_repoqa_dataset, _load_scorer, _repo_info,
        )

        native_task = _load_native_task(self.dataset_root, item.instance_id)
        repoqa_dataset = _load_raw_repoqa_dataset(self.dataset_root)
        verdict, _best_target, similarity = _load_scorer()(
            item.response.strip(), native_task, _repo_info(repoqa_dataset, native_task), False,
        )
        value = float(str(getattr(verdict, "value", verdict)) == "best_match" and float(similarity or 0) >= 0.8)
        return QualityObservation(
            request_id=item.request_id, candidate_id=item.candidate_id,
            metric_id=self.capability.metric_id, value=value, value_scale=self.capability.value_scale or "unit",
            assessor_id=self.capability.signal_id, assessor_version=self.capability.version,
            sensor_class=SensorClass.ORACLE, provenance=Provenance.DERIVED,
            cost=SensorCost(None, Provenance.UNAVAILABLE, TokenUsage(0, Provenance.DERIVED)),
            uses_reference_data=True,
        )


class RepoQADatasetAdapter(LocalDatasetPackage):
    def semantic_quality_assessors(self) -> tuple[SignalCapability, ...]:
        return (SignalCapability(
            signal_id="repoqa-reference-scorer",
            version="1",
            metric_id="repoqa_correctness",
            sensor_class="oracle",
            value_provenance="derived",
            cost=SignalCost(None, "unavailable", 0, "derived"),
            value_scale="binary",
            uses_reference_data=True,
            deployment_scope="reference-data",
        ),)

    def online_assessor(self, signal_id: str) -> object | None:
        capability = next((row for row in self.semantic_quality_assessors()
                           if row.signal_id == signal_id), None)
        return _RepoQAOnlineAssessor(self._root, capability) if capability is not None else None

    def validators(self) -> dict[str, object]:
        from ctxbench.adapters.repoqa.evaluation import evaluate_configured_response
        return {"repoqa-scorer": evaluate_configured_response}

    REPRESENTATION_ARTIFACTS: dict[str, str] = REPRESENTATION_ARTIFACTS

    def __init__(self, dataset_root: str | Path) -> None:
        root = str(Path(dataset_root).resolve())
        super().__init__(
            ExperimentDataset(
                root=root,
                id="ctxbench/repoqa",
                version=self._detect_version(root),
                origin=root,
            )
        )
        self._root: str = root

    @override
    def metadata(self) -> DatasetMetadata:
        return DatasetMetadata(
            name="CTXBench RepoQA",
            description=(
                "RepoQA Search Needle Function dataset adapted to CTXBench with operation-mediated "
                "context access and deterministic RepoQA scoring."
            ),
            domain="software-repository",
            intended_uses="Evaluate context provisioning strategies for code-context retrieval tasks.",
            limitations="Tool access is limited to the declared RepoQA operation surface. Scoring uses the deterministic RepoQA scorer.",
            license_url=None,
            citation_url=None,
        )

    @override
    def identity(self) -> str:
        return "ctxbench/repoqa"

    @override
    def version(self) -> str:
        return self._detect_version(self._root)

    @override
    def fixtures(self) -> object:
        return self._root

    def resolve_surface(self, surface: SurfaceSpec) -> ResolvedSurface:
        if surface.type == "full_context":
            return ResolvedSurface(declaration=surface)
        unknown = [name for name in surface.operations if name not in REPOQA_ALL_OPERATIONS]
        if unknown:
            raise ValueError(f"Unknown RepoQA operations: {', '.join(unknown)}")
        return ResolvedSurface(declaration=surface, operations=tuple(surface.operations))

    def tool_provider(self, *, allowed_operations: list[str] | None = None) -> object | None:
        return RepoQAToolService(contexts_dir=self.dataset_paths.contexts, allowed_operations=allowed_operations)

    def mcp_server(self, *, allowed_operations: list[str] | None = None) -> object:
        return build_repoqa_mcp_server(contexts_dir=self.dataset_paths.contexts, allowed_operations=allowed_operations)

    def dataset_instructions(
        self,
    ) -> str | None:
        for filename in ("dataset-instructions.txt", "dataset-instructions.md"):
            path = Path(self._root) / filename
            if path.exists() and not path.is_dir():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    return content
        return None

    @override
    def get_task(self, task_id: str) -> TaskPayload:
        task = self.get_task_model(task_id)
        return TaskPayload(
            task_id=task.id,
            statement=task.statement,
            tags=list(task.tags),
            validation_type=task.validation.type,
            validation_config=task.validation.validation_config(),
            context_blocks=list(task.contextBlocks),
            metadata={"source": "tasks.json"},
        )

    @override
    def get_context(
        self,
        instance_id: str,
        task_id: str,
        representation: str | None = None,
    ) -> ContextPayload:
        del task_id

        filename = self.REPRESENTATION_ARTIFACTS.get(representation, representation)
        path = Path(self.dataset_paths.contexts) / instance_id / filename

        if not path.exists():
            raise UnsupportedRepresentationError(
                f"Representation '{representation}' not available for instance '{instance_id}'"
            )

        if path.suffix == ".json":
            content = load_json(path)
            content_type = "application/json"
        else:
            content = path.read_text(encoding="utf-8")
            content_type = "text/plain"

        return ContextPayload(
            role="context",
            representation=representation,
            content=content,
            content_type=content_type,
            metadata={
                "instance_id": instance_id,
                "artifact": filename,
            },
        )

    @override
    def get_evidence(self, instance_id: str, task_id: str) -> EvidencePayload:
        task = self.get_task(task_id)
        blocks_path = Path(self.dataset_paths.contexts) / instance_id / "blocks.json"
        blocks = load_json(blocks_path)
        task_instance = self.get_task_instance(instance_id, task_id)

        return EvidencePayload(
            role="evidence",
            task={
                "task_id": task.task_id,
                "statement": task.statement,
                "context_blocks": task.context_blocks,
            },
            evidence=blocks,
            task_instance=task_instance,
            metadata={
                "instance_id": instance_id,
                "task_id": task_id,
            },
        )

    @override
    def get_oracle(self, instance_id: str, task_id: str) -> object:
        del task_id
        oracle_path = Path(self.dataset_paths.contexts) / instance_id / "oracle.json"
        if not oracle_path.exists():
            return super().get_oracle(instance_id, task_id)
        return load_json(oracle_path)

    @override
    def capability_report(self) -> DatasetCapabilityReport:
        report = validate_package(self)
        report.identity = self.identity()
        report.version = self.version()
        report.origin = self.origin()
        report.materialized_path = self._root
        return report

    @staticmethod
    def _detect_version(dataset_root: str | Path) -> str:
        manifest_path = Path(dataset_root) / "ctxbench.dataset.json"
        if manifest_path.exists():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            value = payload.get("datasetVersion") or payload.get("version")
            if isinstance(value, str) and value.strip():
                return value.strip()

        tasks_path = Path(dataset_root) / "tasks.json"
        if tasks_path.exists():
            payload = json.loads(tasks_path.read_text(encoding="utf-8"))
            value = payload.get("version")
            if isinstance(value, str) and value.strip():
                return value.strip()

        return "unknown"
