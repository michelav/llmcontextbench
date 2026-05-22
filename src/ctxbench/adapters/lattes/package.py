from __future__ import annotations

import json
from pathlib import Path

from ctxbench.benchmark.models import ExperimentDataset
from ctxbench.dataset.capabilities import DatasetCapabilityReport
from ctxbench.dataset.errors import UnsupportedRepresentationError
from ctxbench.dataset.payloads import (
    ORACLE_UNAVAILABLE,
    ContextPayload,
    EvidencePayload,
    OracleUnavailable,
    TaskPayload,
)
from ctxbench.dataset.provider import LocalDatasetPackage
from ctxbench.dataset.validation import validate_package
from ctxbench.adapters.lattes.mcp_server import build_lattes_mcp_server
from ctxbench.adapters.lattes.tools import LattesToolService
from ctxbench.util.fs import load_json


FORMAT_ARTIFACTS = {
    "html": "clean.html",
    "raw_html": "raw.html",
    "cleaned_html": "clean.html",
    "clean_html": "clean.html",
    "json": "parsed.json",
    "parsed_json": "parsed.json",
    "blocks": "blocks.json",
}


class LattesDatasetAdapter(LocalDatasetPackage):
    FORMAT_ARTIFACTS = FORMAT_ARTIFACTS

    def __init__(self, dataset_root: str | Path) -> None:
        root = str(Path(dataset_root).resolve())
        super().__init__(
            ExperimentDataset(
                root=root,
                id="ctxbench/lattes",
                version=self._detect_version(root),
                origin=root,
            )
        )
        self._root = root

    def identity(self) -> str:
        return "ctxbench/lattes"

    def version(self) -> str:
        return self.dataset_paths.version or self._detect_version(self._root)

    def fixtures(self) -> object:
        return self._root

    def tool_provider(self) -> object | None:
        return LattesToolService(contexts_dir=self.dataset_paths.contexts)

    def mcp_server(self) -> object:
        return build_lattes_mcp_server(contexts_dir=self.dataset_paths.contexts)

    def get_task(self, task_id: str) -> TaskPayload:
        task = self.get_task_model(task_id)
        return TaskPayload(
            task_id=task.id,
            statement=task.statement,
            tags=list(task.tags),
            validation_type=task.validation.type,
            context_blocks=list(task.contextBlocks),
        )

    def get_context(
        self,
        instance_id: str,
        task_id: str,
        representation: str,
    ) -> ContextPayload:
        del task_id
        filename = self.FORMAT_ARTIFACTS.get(representation, representation)
        path = Path(self.dataset_paths.contexts) / instance_id / filename
        if not path.exists():
            raise UnsupportedRepresentationError(
                f"Representation '{representation}' not available for instance '{instance_id}'"
            )
        content_type = "text/html" if filename.endswith(".html") else "application/json"
        content = path.read_text(encoding="utf-8") if content_type == "text/html" else json.dumps(load_json(path))
        return ContextPayload(
            role="context",
            representation=representation,
            content=content,
            content_type=content_type,
        )

    def get_evidence(self, instance_id: str, task_id: str) -> EvidencePayload:
        task = self.get_task(task_id)
        blocks = self.get_context_blocks(instance_id)
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
        )

    def get_oracle(self, instance_id: str, task_id: str) -> OracleUnavailable:
        del instance_id, task_id
        return ORACLE_UNAVAILABLE

    def capability_report(self) -> DatasetCapabilityReport:
        report = validate_package(self)
        report.identity = self.identity()
        report.version = self.version()
        report.origin = self.origin()
        report.materialized_path = self._root
        return report

    @staticmethod
    def _detect_version(dataset_root: str | Path) -> str:
        root = Path(dataset_root)
        tasks_payload = root / "tasks.json"
        instances_payload = root / "tasks.instance.json"
        if tasks_payload.exists():
            import json

            payload = json.loads(tasks_payload.read_text(encoding="utf-8"))
            version = payload.get("version")
            if isinstance(version, str) and version.strip():
                return version.strip()
        if instances_payload.exists():
            import json

            payload = json.loads(instances_payload.read_text(encoding="utf-8"))
            reference_date = payload.get("referenceDate")
            if isinstance(reference_date, str) and reference_date.strip():
                return reference_date.strip()
            version = payload.get("version")
            if isinstance(version, str) and version.strip():
                return version.strip()
        return "unknown"

    def dataset_instructions(self) -> str | None:
        path = Path(self._root) / "dataset-instructions.txt"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8").strip() or None
