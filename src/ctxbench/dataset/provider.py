from __future__ import annotations

from pathlib import Path

from ctxbench.benchmark.models import DatasetProvenance, Experiment, ExperimentDataset
from ctxbench.dataset.capabilities import DatasetCapabilityReport
from ctxbench.dataset.contexts import artifact_name_for_format
from ctxbench.dataset.package import DatasetMetadata
from ctxbench.dataset.payloads import (
    ORACLE_UNAVAILABLE,
    ContextPayload,
    EvidencePayload,
    OracleUnavailable,
    TaskPayload,
)
from ctxbench.dataset.questions import (
    Question,
    QuestionDataset,
    QuestionInstance,
    QuestionInstanceDataset,
    QuestionInstanceEntry,
)
from ctxbench.util.fs import load_json


class LocalDatasetPackage:
    def __init__(self, dataset_paths: ExperimentDataset) -> None:
        self.dataset_paths = dataset_paths
        if not dataset_paths.root:
            raise ValueError("LocalDatasetPackage requires a dataset root.")
        self._questions = QuestionDataset.model_validate(load_json(dataset_paths.questions))
        self._question_instances = self._load_question_instances(dataset_paths.question_instances)

    @classmethod
    def from_experiment(cls, experiment: Experiment, base_dir: str | Path) -> "LocalDatasetPackage":
        base = Path(base_dir)
        dataset = ExperimentDataset(root=str((base / experiment.dataset.root).resolve()))
        return cls(dataset)

    @classmethod
    def from_dataset(cls, dataset: ExperimentDataset | DatasetProvenance) -> "LocalDatasetPackage":
        if isinstance(dataset, DatasetProvenance):
            dataset = ExperimentDataset(
                root=dataset.materialized_path,
                id=dataset.id,
                version=dataset.version,
                origin=dataset.origin,
            )
        return cls(dataset)

    def metadata(self) -> DatasetMetadata:
        return DatasetMetadata(
            name=self.identity(),
            description=self._questions.description or "Local dataset root",
            domain=self._questions.domain or "unknown",
            intended_uses="Local planning and evaluation fixtures.",
            limitations="Provenance is derived from the on-disk dataset root.",
            license_url=None,
            citation_url=None,
        )

    def identity(self) -> str:
        if self.dataset_paths.id:
            return self.dataset_paths.id
        if self._questions.datasetId:
            return self._questions.datasetId
        return Path(self.dataset_paths.root or "").name or "local-dataset"

    def version(self) -> str:
        return (
            self._questions.version
            or self._question_instances.version
            or self.dataset_paths.version
            or "local"
        )

    def origin(self) -> str | None:
        return self.dataset_paths.origin or self.dataset_paths.root

    def list_question_ids(self) -> list[str]:
        return [question.id for question in self._questions.questions]

    def list_task_ids(self) -> list[str]:
        return self.list_question_ids()

    def list_instance_ids(self) -> list[str]:
        return [instance.instanceId for instance in self._question_instances.instances]

    def list_context_ids(self, format_name: str | None = None) -> list[str]:
        return self.list_instance_ids()

    def get_question(self, question_id: str) -> Question:
        for question in self._questions.questions:
            if question.id == question_id:
                return question
        raise KeyError(f"Unknown question id: {question_id}")

    def get_task(self, task_id: str) -> TaskPayload:
        question = self.get_question(task_id)
        return TaskPayload(
            task_id=question.id,
            statement=question.question,
            tags=list(question.tags),
            validation_type=question.validation.type,
            context_blocks=list(question.contextBlock),
            metadata={"source": "questions.json"},
        )

    def get_instance(self, instance_id: str) -> QuestionInstance:
        for instance in self._question_instances.instances:
            if instance.instanceId == instance_id:
                return instance
        raise KeyError(f"Unknown instance id: {instance_id}")

    def get_question_instance(self, question_id: str, context_id: str) -> QuestionInstanceEntry | None:
        instance = self.get_instance(context_id)
        return instance.get_question(question_id)

    def get_task_instance(self, instance_id: str, task_id: str) -> dict[str, object] | None:
        question_instance = self.get_question_instance(task_id, instance_id)
        if question_instance is None:
            return None
        return {"parameters": dict(question_instance.parameters)}

    def list_question_ids_for_instance(self, instance_id: str) -> list[str]:
        instance = self.get_instance(instance_id)
        return [item.id for item in instance.questions]

    def get_instance_dir(self, instance_id: str) -> Path:
        path = Path(self.dataset_paths.contexts) / instance_id
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"Missing context directory for instance '{instance_id}': {path}")
        return path

    def get_context_artifact_path(self, instance_id: str, format_name: str) -> Path:
        filename = artifact_name_for_format(format_name)
        path = self.get_instance_dir(instance_id) / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing context artifact: {path}")
        return path

    def _read_context_text(self, context_id: str, format_name: str) -> str:
        path = self.get_context_artifact_path(context_id, format_name)
        return path.read_text(encoding="utf-8")

    def get_context(
        self,
        instance_id: str,
        task_id: str,
        representation: str | None = None,
    ) -> ContextPayload | str:
        if representation is None:
            return self._read_context_text(instance_id, task_id)
        return ContextPayload(
            role="context",
            representation=representation,
            content=self.get_context_artifact(instance_id, task_id, "inline", representation),
            metadata={"instance_id": instance_id, "task_id": task_id},
        )

    def get_context_artifact(
        self,
        instance_id: str,
        task_id: str,
        strategy: str,
        format_name: str,
    ) -> object:
        del task_id, strategy
        path = self.get_context_artifact_path(instance_id, format_name)
        if path.suffix == ".json":
            return load_json(path)
        return path.read_text(encoding="utf-8")

    def get_context_blocks(self, instance_id: str) -> dict[str, object]:
        instance = self.get_instance(instance_id)
        path = Path(self.dataset_paths.root) / instance.contextBlocks if instance.contextBlocks else None
        if path is None or not path.exists() or path.is_dir():
            path = self.get_instance_dir(instance_id) / "blocks.json"
        payload = load_json(path)
        if not isinstance(payload, dict):
            raise ValueError(f"Context blocks must be a JSON object: {path}")
        return payload

    def get_evidence_artifact(self, instance_id: str, task_id: str) -> object:
        question = self.get_question(task_id)
        question_instance = self.get_question_instance(task_id, instance_id)
        return {
            "question": question.model_dump(mode="python"),
            "questionInstance": question_instance.model_dump(mode="python") if question_instance is not None else None,
            "contextBlocks": self.get_context_blocks(instance_id),
        }

    def get_evidence(self, instance_id: str, task_id: str) -> EvidencePayload:
        artifact = self.get_evidence_artifact(instance_id, task_id)
        if not isinstance(artifact, dict):
            return EvidencePayload(role="evidence", task={}, evidence=artifact)
        task = self.get_task(task_id)
        return EvidencePayload(
            role="evidence",
            task={
                "task_id": task.task_id,
                "statement": task.statement,
                "context_blocks": task.context_blocks,
            },
            task_instance=artifact.get("questionInstance"),
            evidence=artifact.get("contextBlocks", {}),
            metadata={"instance_id": instance_id, "task_id": task_id},
        )

    def get_oracle(self, instance_id: str, task_id: str) -> OracleUnavailable:
        return ORACLE_UNAVAILABLE

    def fixtures(self) -> object:
        return {
            "root": self.dataset_paths.root,
            "questions": len(self._questions.questions),
            "instances": len(self._question_instances.instances),
        }

    def capability_report(self) -> DatasetCapabilityReport:
        return DatasetCapabilityReport(
            identity=self.identity(),
            version=self.version(),
            origin=self.origin(),
            resolved_revision=None,
            materialized_path=self.dataset_paths.root,
            content_hash=None,
            metadata=self.metadata(),
            mandatory_capabilities={
                "metadata": True,
                "identity": True,
                "version": True,
                "list_instance_ids": True,
                "list_task_ids": True,
                "get_task": True,
                "get_context": True,
                "get_evidence": True,
            },
            optional_capabilities={
                "get_oracle": True,
                "get_task_instance": True,
                "tool_provider": False,
                "fixtures": True,
            },
            contributed_tools=None,
            evaluation_helpers=None,
            strategy_descriptors=[],
            missing_mandatory=[],
            nonconformant_descriptors=[],
            conformant=True,
        )

    def tool_provider(self) -> object | None:
        return None

    def evaluation_helpers(self) -> object | None:
        return None

    def strategy_descriptors(self) -> list[object] | None:
        return None

    def _load_question_instances(self, path: str | None) -> QuestionInstanceDataset:
        if not path or not Path(path).exists():
            return QuestionInstanceDataset(datasetId="missing", instances=[])
        raw = load_json(path)
        if not isinstance(raw, dict):
            raise ValueError("Question instances dataset must be a JSON object.")
        return QuestionInstanceDataset.model_validate(raw)


class DatasetProvider(LocalDatasetPackage):
    # deprecated: no longer called by lifecycle phases; retained for Spec 004 migration safety
    pass
