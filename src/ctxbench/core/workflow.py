"""Shared workflow contract and kind resolution.

Benchmark and adaptive workflows implement ``Workflow``. Callers (commands and
``ctxbench.api``) obtain the implementation from a ``WorkflowRegistry``; the registry is
the only place that reads the workflow kind.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Iterator, Mapping, Protocol, Sequence

from ctxbench.util.fs import load_json


JSON = None | bool | int | float | str | list["JSON"] | dict[str, "JSON"]

DEFAULT_KIND = "benchmark"
KIND_FIELD = "workflowKind"


@dataclass(frozen=True, slots=True)
class PlanOutcome:
    workflow_id: str
    workflow_kind: str
    root: Path
    plan_path: Path
    planned: int
    summary: str


@dataclass(frozen=True, slots=True)
class RunStatus:
    workflow_id: str
    workflow_kind: str
    root: Path
    counts: Mapping[str, int] = field(default_factory=dict)
    report: tuple[str, ...] = ()   # rendered status table, one entry per output line


@dataclass(frozen=True, slots=True)
class ExecuteOptions:
    retry_uncertain: bool = False
    force: bool = False
    selector: Any = None
    progress: bool = False
    plan_path: Path | None = None  # explicit plan file inside the run directory, if any


@dataclass(frozen=True, slots=True)
class ExecuteOutcome:
    workflow_id: str
    workflow_kind: str
    counts: Mapping[str, int] = field(default_factory=dict)
    summary: str = ""


@dataclass(frozen=True, slots=True)
class MetricsOptions:
    output_dir: Path
    group_by: str | None = None
    force: bool = False
    selector: Any = None
    evaluation_status: tuple[str, ...] = ()
    not_evaluation_status: tuple[str, ...] = ()
    command: str | None = None


@dataclass(frozen=True, slots=True)
class MetricsOutcome:
    workflow_kind: str
    output_dir: Path
    counts: Mapping[str, int] = field(default_factory=dict)
    summary: str = ""


class StatusGroupingError(ValueError):
    """Unsupported ``by`` grouping. Carries the report lines produced before the grouping."""

    def __init__(self, message: str, report: Sequence[str] = ()):
        super().__init__(message)
        self.report = tuple(report)


class Workflow(Protocol):
    kind: ClassVar[str]

    def load_definition(self, source: str | Path | Mapping[str, JSON], *, logger: Any = None) -> Any: ...
    def plan(self, definition: Any, *, output: Path | None, cache_dir: Path | None,
             plugin_paths: Sequence[Path] = (), logger: Any = None,
             progress: bool = False) -> PlanOutcome: ...
    def status(self, root: Path, *, by: str | None = None) -> RunStatus: ...
    def execute(self, root: Path, *, options: ExecuteOptions, logger: Any = None) -> ExecuteOutcome: ...
    def prepare_responses(self, root: Path) -> Mapping[str, Any]: ...
    def responses(self, root: Path) -> Iterator[Mapping[str, JSON]]: ...
    def metric_tables(self, root: Path) -> Mapping[str, Sequence[Mapping[str, JSON]]]: ...
    def write_metrics(self, roots: Sequence[str], *, options: MetricsOptions,
                      logger: Any = None) -> MetricsOutcome: ...


class WorkflowRegistry:
    """Resolve definition and run kinds in one place."""

    def __init__(self, workflows: Sequence[Workflow]):
        by_kind = {workflow.kind: workflow for workflow in workflows}
        if len(by_kind) != len(workflows):
            raise ValueError("workflow kinds must be unique")
        if DEFAULT_KIND not in by_kind:
            raise ValueError("a benchmark workflow must be registered")
        self._workflows = by_kind

    @property
    def default(self) -> Workflow:
        return self._workflows[DEFAULT_KIND]

    def get(self, kind: str) -> Workflow:
        try:
            return self._workflows[kind]
        except KeyError as exc:
            raise ValueError(f"unsupported workflow kind: {kind}") from exc

    def for_definition(self, header: Any) -> Workflow:
        """Workflow of a definition (or manifest) header; headers without a kind are benchmarks."""
        if not isinstance(header, Mapping):
            return self.default
        kind = header.get(KIND_FIELD, DEFAULT_KIND)
        if not isinstance(kind, str):
            raise ValueError(f"{KIND_FIELD} must be a string")
        return self.get(kind)

    def for_run(self, root: str | Path) -> Workflow:
        """Workflow of a run directory. A missing manifest is reported by the default workflow."""
        manifest_path = Path(root) / "manifest.json"
        if not manifest_path.exists():
            return self.default
        manifest = load_json(manifest_path)
        if not isinstance(manifest, Mapping):
            raise ValueError(f"Invalid manifest: {manifest_path}")
        return self.for_definition(manifest)

    def for_inputs(self, roots: Sequence[str | Path]) -> Workflow:
        """Workflow for a metrics invocation. Several inputs are merged by the default workflow."""
        if len(roots) != 1:
            return self.default
        manifest_path = Path(roots[0]).expanduser() / "manifest.json"
        if not manifest_path.exists():
            return self.default
        return self.for_definition(load_json(manifest_path))
