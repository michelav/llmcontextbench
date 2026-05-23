from __future__ import annotations

import json
from pathlib import Path
from typing import override

from ctxbench.benchmark.models import ExperimentDataset
from ctxbench.dataset.capabilities import DatasetCapabilityReport
from ctxbench.dataset.errors import UnsupportedRepresentationError
from ctxbench.dataset.package import DatasetMetadata
from ctxbench.dataset.payloads import ContextPayload, EvidencePayload, TaskPayload
from ctxbench.dataset.provider import LocalDatasetPackage
from ctxbench.dataset.validation import validate_package
from ctxbench.util.fs import load_json


FORMAT_ARTIFACTS = {
    "code": "code_context.txt",
    "code_context": "code_context.txt",
    "text": "code_context.txt",
    "json": "parsed.json",
    "parsed": "parsed.json",
    "parsed_json": "parsed.json",
    "blocks": "blocks.json",
    "oracle": "oracle.json"
}


class RepoQADatasetAdapter(LocalDatasetPackage):
    FORMAT_ARTIFACTS: dict[str, str] = FORMAT_ARTIFACTS

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
            description="RepoQA Search Needle Function dataset adapted to CTXBench.",
            domain="software-repository",
            intended_uses="Evaluate context provisioning strategies for code-context retrieval tasks.",
            limitations="Initial adapter supports inline context. Deterministic RepoQA scoring is added later.",
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

    def dataset_instructions(
        self,
    ) -> str | None:
        path = Path(self._root) / "dataset-instructions.txt"
        if not path.exists() or path.is_dir():
            return None
        content = path.read_text(encoding="utf-8").strip()
        return content or None

    @override
    def get_task(self, task_id: str) -> TaskPayload:
        task = self.get_task_model(task_id)
        return TaskPayload(
            task_id=task.id,
            statement=task.statement,
            tags=list(task.tags),
            validation_type=task.validation.type,
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

        filename = self.FORMAT_ARTIFACTS.get(representation, representation)
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
