"""Public plan and run handles.

Every function here returns a typed result or raises a ``CtxbenchError``; none prints.
Dispatch between workflow kinds goes through the workflow registry only.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from ctxbench.api.errors import (
    ArtifactError, CapabilityError, CtxbenchError, DefinitionError, ExecutionStateError, RunNotFoundError,
)
from ctxbench.api.workflows import registry
from ctxbench.core.workflow import (
    ExecuteOptions, ExecuteOutcome, MetricsOptions, MetricsOutcome, RunStatus, Workflow,
)
from ctxbench.util.fs import load_json
from ctxbench.util.logging import PhaseLogger


@dataclass(frozen=True, slots=True)
class PhaseOutcome:
    """Result of the evaluation or export phase."""
    phase: str
    root: Path
    messages: tuple[str, ...] = ()


class _NullStream:
    def write(self, _text: str) -> int:
        return 0

    def flush(self) -> None:
        return None


def _silent_logger() -> PhaseLogger:
    return PhaseLogger(stream=_NullStream())  # type: ignore[arg-type]


@contextmanager
def _errors(default: type[CtxbenchError]):
    """Translate internal exceptions into the public hierarchy, keeping the cause."""
    from ctxbench.core.errors import CapabilityUnavailableError, InvalidDefinitionError
    from ctxbench.dataset.conflicts import AmbiguousDatasetError
    from ctxbench.dataset.errors import AdapterUnavailableError
    from ctxbench.dataset.resolver import DatasetNotFoundError, MultiDatasetError
    try:
        yield
    except CtxbenchError:
        raise
    except (DatasetNotFoundError, AmbiguousDatasetError, MultiDatasetError, AdapterUnavailableError,
            CapabilityUnavailableError) as exc:
        raise CapabilityError(str(exc)) from exc
    except InvalidDefinitionError as exc:
        raise DefinitionError(str(exc)) from exc
    except FileNotFoundError as exc:
        raise ArtifactError(str(exc)) from exc
    except ValueError as exc:
        raise default(str(exc)) from exc
    except Exception as exc:
        if type(exc).__name__ == "ValidationError":   # jsonschema and model validation errors
            message = getattr(exc, "message", None) or str(exc)
            raise default(str(message)) from exc
        raise


def plan(source: Any, *, output: str | Path | None = None,
         cache_dir: str | Path | None = None, plugin_paths: Sequence[str | Path] = (),
         logger: PhaseLogger | None = None, progress: bool = False) -> "Run":
    """Plan a benchmark or adaptive definition and return its run handle.

    ``source`` is a definition path, an in-memory definition mapping, or a definition object
    (for example ``AdaptiveExperiment``). Relative paths inside an
    in-memory definition resolve against the current working directory. No provider is called.
    """
    logger = logger or _silent_logger()
    with _errors(DefinitionError):
        definition_source: Any = source
        if isinstance(source, Mapping):
            workflow = registry.for_definition(source)
        elif isinstance(source, (str, Path)):
            definition_source = str(source)
            workflow = registry.for_definition(load_json(Path(source).expanduser().resolve()))
        else:
            workflow = registry.for_object(source)
        definition = workflow.load_definition(definition_source, logger=logger)
    with _errors(ExecutionStateError):
        outcome = workflow.plan(
            definition,
            output=Path(output).expanduser() if output else None,
            cache_dir=Path(cache_dir) if cache_dir else None,
            plugin_paths=tuple(Path(item) for item in plugin_paths),
            logger=logger, progress=progress,
        )
    return Run(outcome.root, workflow, outcome.workflow_id)


def open_run(path: str | Path) -> "Run":
    """Return the handle of an already planned run directory."""
    root = Path(path).expanduser().resolve()
    if not (root / "manifest.json").is_file():
        raise RunNotFoundError(f"No planned run found at {root}")
    with _errors(ArtifactError):
        workflow = registry.for_run(root)
        manifest = load_json(root / "manifest.json")
    workflow_id = str(manifest.get("experimentId", "unknown")) if isinstance(manifest, Mapping) else "unknown"
    return Run(root, workflow, workflow_id)


def summarize(runs, *, signals):
    """Return artifact-only adaptive run summaries for research scripts."""
    from ctxbench.analysis.summarize import summarize as summarize_runs
    return summarize_runs(runs, signals=signals)


def headroom(run, *, signal, objective="min", by=None):
    """Compare the best static benchmark candidate with its per-request oracle."""
    from ctxbench.analysis.headroom import headroom as analyze_headroom
    return analyze_headroom(run, signal=signal, objective=objective, by=by)


class Run:
    """Handle for lifecycle operations on one frozen output directory."""

    def __init__(self, root: Path, workflow: Workflow, workflow_id: str):
        self.root = Path(root).resolve()
        self._workflow = workflow
        self.workflow_id = workflow_id

    @property
    def kind(self) -> str:
        return self._workflow.kind

    @property
    def manifest(self) -> Mapping[str, Any]:
        with _errors(ArtifactError):
            return load_json(self.root / "manifest.json")

    # ---- lifecycle ---------------------------------------------------------------------

    def status(self, *, by: str | None = None) -> RunStatus:
        with _errors(ArtifactError):
            return self._workflow.status(self.root, by=by)

    def execute(self, *, retry_uncertain: bool = False, force: bool = False, selector: Any = None,
                logger: PhaseLogger | None = None, progress: bool = False,
                plugin_paths: Sequence[str | Path] = ()) -> ExecuteOutcome:
        """Run answer generation. This is the only call that invokes generation providers."""
        options = ExecuteOptions(retry_uncertain=retry_uncertain, force=force, selector=selector,
                                 progress=progress, plugin_paths=tuple(Path(item) for item in plugin_paths))
        with _errors(ExecutionStateError):
            return self._workflow.execute(self.root, options=options, logger=logger or _silent_logger())

    def evaluate(self, **options: Any) -> PhaseOutcome:
        """Evaluate delivered responses. This is the only call that invokes judge providers."""
        from ctxbench.phases.evaluation import run_evaluation
        return self._phase("evaluate", run_evaluation, self.root / "responses.jsonl", options)

    def export(self, **options: Any) -> PhaseOutcome:
        from ctxbench.phases.export import run_export
        return self._phase("export", run_export, self.root / "evals.jsonl", options)

    def metrics(self, *, output: str | Path | None = None, group_by: str | None = None,
                force: bool = False, selector: Any = None, evaluation_status: tuple[str, ...] = (),
                not_evaluation_status: tuple[str, ...] = (),
                logger: PhaseLogger | None = None) -> MetricsOutcome:
        options = MetricsOptions(
            output_dir=Path(output).expanduser() if output else self.root / "metrics",
            group_by=group_by, force=force, selector=selector,
            evaluation_status=evaluation_status, not_evaluation_status=not_evaluation_status,
        )
        with _errors(ExecutionStateError):
            return self._workflow.write_metrics([str(self.root)], options=options,
                                                logger=logger or _silent_logger())

    # ---- artifact readers --------------------------------------------------------------

    def metric_tables(self) -> Mapping[str, Sequence[Mapping[str, Any]]]:
        with _errors(ArtifactError):
            return self._workflow.metric_tables(self.root)

    def responses(self) -> Iterator[Mapping[str, Any]]:
        return self._workflow.responses(self.root)

    def trials(self) -> Iterator[Mapping[str, Any]]:
        return self._kind_specific("trials")

    def requests(self) -> Iterator[Mapping[str, Any]]:
        return self._kind_specific("requests")

    def attempts(self) -> Iterator[Mapping[str, Any]]:
        return self._kind_specific("attempts")

    # ---- helpers -----------------------------------------------------------------------

    def _kind_specific(self, name: str):
        operation = getattr(self._workflow, name, None)
        if operation is None:
            raise ExecutionStateError(f"A {self.kind} run does not expose {name}.")
        return operation(self.root)

    def _phase(self, phase: str, function, source: Path, options: dict[str, Any]) -> PhaseOutcome:
        messages: list[str] = []
        with _errors(ExecutionStateError):
            code = function(str(source), prepare=self._workflow.prepare_responses,
                            emit=messages.append, **options)
        if code != 0:
            raise ExecutionStateError(f"{phase} failed: " + ("; ".join(messages) or f"exit code {code}"))
        return PhaseOutcome(phase, self.root, tuple(messages))
