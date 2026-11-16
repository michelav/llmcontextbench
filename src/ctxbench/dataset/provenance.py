"""Dataset identity and materialization provenance shared by workflows and adapters."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ctxbench._compat import BaseModel, ValidationError


class DatasetProvenance(BaseModel):
    id: str
    version: str
    origin: str | None = None
    resolved_revision: str | None = None
    content_hash: str | None = None
    materialized_path: str | None = None

    @classmethod
    def model_validate(cls, data: Any) -> "DatasetProvenance":
        if isinstance(data, cls):
            return data
        # Accept the benchmark's dataset reference by its public attributes without
        # importing that workflow model into the shared dataset layer.
        if not isinstance(data, (str, dict)) and hasattr(data, "root"):
            root = getattr(data, "root", None)
            return cls(
                id=getattr(data, "id", None) or (Path(root).name if root else "local-dataset"),
                version=getattr(data, "version", None) or "local",
                origin=getattr(data, "origin", None) or root,
                materialized_path=root,
            )
        if isinstance(data, str):
            root = str(Path(data).expanduser())
            return cls(id=Path(root).name or "local-dataset", version="local",
                       origin=root, materialized_path=root)
        if isinstance(data, dict):
            payload = dict(data)
            legacy_paths = {"tasks", "contexts", "task_instances"}
            if legacy_paths & set(payload) and "root" not in payload and "id" not in payload:
                raise ValidationError(
                    "Dataset provenance must reference a dataset root or id/version. "
                    "Put tasks.json and tasks.instance.json in the dataset root "
                    "and context files in <dataset>/context."
                )
            if "root" in payload:
                root = str(payload.get("root") or "")
                return cls(
                    id=str(payload.get("id") or (Path(root).name if root else "local-dataset")),
                    version=str(payload.get("version") or "local"),
                    origin=str(payload.get("origin") or root) if (payload.get("origin") or root) else None,
                    resolved_revision=payload.get("resolvedRevision") or payload.get("resolved_revision"),
                    content_hash=payload.get("contentHash") or payload.get("content_hash"),
                    materialized_path=str(payload.get("materializedPath") or payload.get("materialized_path") or root)
                    if (payload.get("materializedPath") or payload.get("materialized_path") or root) else None,
                )
            if "id" in payload:
                return cls(
                    id=str(payload.get("id") or ""), version=str(payload.get("version") or ""),
                    origin=str(payload.get("origin")) if payload.get("origin") is not None else None,
                    resolved_revision=payload.get("resolvedRevision") or payload.get("resolved_revision"),
                    content_hash=payload.get("contentHash") or payload.get("content_hash"),
                    materialized_path=str(payload.get("materializedPath") or payload.get("materialized_path"))
                    if (payload.get("materializedPath") or payload.get("materialized_path")) is not None else None,
                )
        raise ValidationError("DatasetProvenance requires an object input.")

    def model_dump(self, mode: str = "python") -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "origin": self.origin,
            "resolvedRevision": self.resolved_revision,
            "contentHash": self.content_hash,
            "materializedPath": self.materialized_path,
        }

    @property
    def root(self) -> str | None:
        return self.materialized_path or self.origin

    @property
    def tasks(self) -> str:
        if not self.root:
            raise ValueError("Dataset tasks path is unavailable without a local materialized path.")
        return str(Path(self.root) / "tasks.json")

    @property
    def contexts(self) -> str:
        if not self.root:
            raise ValueError("Dataset contexts path is unavailable without a local materialized path.")
        return str(Path(self.root) / "context")

    @property
    def task_instances(self) -> str:
        if not self.root:
            raise ValueError("Dataset task_instances path is unavailable without a local materialized path.")
        return str(Path(self.root) / "tasks.instance.json")


__all__ = ["DatasetProvenance"]
