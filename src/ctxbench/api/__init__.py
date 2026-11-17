"""Public in-process API for planning and managing benchmark and adaptive runs."""
from ctxbench.api.errors import (
    ArtifactError, CapabilityError, CtxbenchError, DefinitionError, ExecutionStateError, RunNotFoundError,
)
from ctxbench.api.run import PhaseOutcome, Run, headroom, open_run, plan, summarize
from ctxbench.adaptive.definition import (
    Acceptance, AdaptiveExperiment, Candidate, Configuration, Disturbance, Goal, Model,
    PolicyRef, Scenario, SignalRef, Window, WorkloadRequest,
)
from ctxbench.api.dataset import load_dataset
from ctxbench.adaptive.policy import CandidateRef, Decision, Policy, PolicyContractError
from ctxbench.core.workflow import ExecuteOutcome, MetricsOutcome, RunStatus
from ctxbench.workload.builder import DatasetHandle, Segment, Workload

__all__ = [
    "ArtifactError", "CapabilityError", "CtxbenchError", "DefinitionError", "ExecuteOutcome",
    "ExecutionStateError", "MetricsOutcome", "PhaseOutcome", "Run", "RunNotFoundError", "RunStatus",
    "AdaptiveExperiment", "CandidateRef", "Decision", "Policy", "PolicyContractError",
    "Model", "Configuration", "Candidate", "PolicyRef", "Window", "Goal", "Acceptance",
    "SignalRef", "Disturbance", "Scenario", "WorkloadRequest", "DatasetHandle", "Segment", "Workload",
    "load_dataset",
    "open_run", "plan", "summarize", "headroom",
]
