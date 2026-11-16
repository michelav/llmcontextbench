"""Workflow registry construction."""
from ctxbench.adaptive.workflow import AdaptiveWorkflow
from ctxbench.benchmark.workflow import BenchmarkWorkflow
from ctxbench.core.workflow import WorkflowRegistry


def build_registry() -> WorkflowRegistry:
    return WorkflowRegistry((BenchmarkWorkflow(), AdaptiveWorkflow()))


registry = build_registry()
