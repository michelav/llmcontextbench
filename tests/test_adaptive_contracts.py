from __future__ import annotations

from pathlib import Path

import pytest

from ctxbench.adapters.repoqa.package import RepoQADatasetAdapter
from ctxbench.adaptive.sensors import (
    MinimumResponseLengthSensor,
    QualityObservation,
    SensorClass,
)
from ctxbench.core.provenance import Provenance, TokenUsage
from ctxbench.benchmark.models import ExperimentDataset
from ctxbench.core.provisioning import ProvisioningConfiguration
from ctxbench.dataset.capabilities import (
    DatasetCapabilityReport,
    FeatureCapability,
    FeaturePartitionCapability,
    RequestFeatureSchema,
    SignalCapability,
    SignalCost,
)
from ctxbench.dataset.provider import LocalDatasetPackage
from ctxbench.runtime.disturbances import (
    DisturbanceKind, DisturbanceSpec, RuntimeComponent, ToolRuntimeDisturbance,
)
from ctxbench.runtime.models import RuntimeRequest
from ctxbench.runtime.runtime import ProvisioningRuntime
from ctxbench.ai.models.base import AIResult


ROOT = Path(__file__).resolve().parents[1]


def test_feature_partitions_and_signal_capabilities_across_local_and_repoqa_datasets():
    local = LocalDatasetPackage.from_dataset(ExperimentDataset(
        root=str(ROOT / "tests/fixtures/fake_dataset/dataset"),
        id="ctxbench/fake-dataset", version="0.1.0",
    ))
    repoqa = RepoQADatasetAdapter(ROOT / "tests/fixtures/repoqa_tools_dataset")

    local_report = local.capability_report()
    repoqa_report = repoqa.capability_report()
    assert isinstance(local_report, DatasetCapabilityReport)
    assert local_report.request_feature_schema is not None
    assert repoqa_report.request_feature_schema is not None
    assert local_report.request_feature_schema.schema_id == repoqa_report.request_feature_schema.schema_id

    for package, report in ((local, local_report), (repoqa, repoqa_report)):
        values = package.request_features(package.list_instance_ids()[0], package.list_task_ids()[0])
        partition = report.request_feature_schema.partition_for(values)
        assert partition is not None
        assert partition[0][0] == "context_bytes"
        assert report.response_acceptance_sensors[0].signal_id == "minimum_response_length"

    assert local_report.semantic_quality_assessors == ()
    repoqa_assessor = repoqa_report.semantic_quality_assessors[0]
    assert repoqa_assessor.sensor_class == "oracle"
    assert repoqa_assessor.uses_reference_data
    assert repoqa_assessor.cost.duration_provenance == "unavailable"


def test_feature_schema_rejects_identity_and_invalid_partitions():
    with pytest.raises(ValueError, match="identity and outcome"):
        FeatureCapability("request_id", "category", "reported")
    with pytest.raises(ValueError, match="numeric partitions"):
        FeaturePartitionCapability("context_bytes", (1, 2), ("small",))
    schema = RequestFeatureSchema(
        "schema", "1", (FeatureCapability("context_bytes", "number", "measured", "bytes"),),
        partition_keys=("context_bytes",),
        partitions=(FeaturePartitionCapability("context_bytes", (10,), ("small", "large")),),
    )
    assert schema.partition_for({"context_bytes": 10}) == (("context_bytes", "small"),)
    assert schema.partition_for({"context_bytes": 11}) == (("context_bytes", "large"),)
    assert schema.partition_for({}) is None
    with pytest.raises(ValueError, match="Undeclared"):
        schema.partition_for({"task_id": "leak"})


def test_response_acceptance_and_unavailable_quality_keep_signal_class_and_provenance():
    ticks = iter((10.0, 10.0002))
    observation = MinimumResponseLengthSensor(4, clock=lambda: next(ticks)).observe(
        "request-1", "candidate-a", " ok ",
    )
    assert observation.accepted is False
    assert observation.sensor_class == SensorClass.RESPONSE_ACCEPTANCE
    assert observation.provenance == Provenance.DERIVED
    assert observation.cost.duration_provenance == Provenance.MEASURED
    assert observation.cost.tokens == TokenUsage(0, Provenance.DERIVED)

    unavailable = QualityObservation.unavailable(
        request_id="request-1", candidate_id="candidate-a", metric_id="accuracy",
        value_scale="0..1", assessor_id="semantic-proxy", assessor_version="1",
        sensor_class=SensorClass.SEMANTIC_PROXY,
    )
    assert unavailable.value is None
    assert unavailable.provenance == Provenance.UNAVAILABLE
    assert unavailable.cost.tokens.value is None
    with pytest.raises(ValueError, match="missing quality values"):
        QualityObservation(
            "request-1", "candidate-a", "accuracy", 0.0, "0..1", "proxy", "1",
            SensorClass.SEMANTIC_PROXY, Provenance.UNAVAILABLE,
            unavailable.cost,
        )
    with pytest.raises(ValueError, match="reference-data"):
        QualityObservation(
            "request-1", "candidate-a", "accuracy", 0.8, "0..1", "judge", "1",
            SensorClass.JUDGE, Provenance.REPORTED,
            unavailable.cost,
        )


def test_disturbance_is_named_seeded_and_component_scoped():
    disturbance = DisturbanceSpec(
        name="mcp-degradation", version="1", component=RuntimeComponent.LOCAL_MCP,
        kind=DisturbanceKind.DELAY_AND_FAILURE, first_sequence=2, last_sequence=4,
        seed=17, delay_ms=50, failure_rate=0.1, candidate_ids=("candidate-a",),
    )
    assert disturbance.applies_to(RuntimeComponent.LOCAL_MCP, 2, "candidate-a")
    assert not disturbance.applies_to(RuntimeComponent.LOCAL_FUNCTION, 2, "candidate-a")
    assert not disturbance.applies_to(RuntimeComponent.LOCAL_MCP, 1, "candidate-a")
    assert not disturbance.applies_to(RuntimeComponent.LOCAL_MCP, 2, "candidate-b")
    assert disturbance.decorator(
        component=RuntimeComponent.LOCAL_FUNCTION, sequence=2, candidate_id="candidate-a",
    ) is None

    waits = []
    decorator = disturbance.decorator(
        component=RuntimeComponent.LOCAL_MCP, sequence=2, candidate_id="candidate-a",
        sleeper=waits.append,
    )
    assert decorator is not None

    class ToolRuntime:
        def list_tools(self): return []
        def call_tool(self, name, arguments): return name, arguments
        def close(self): self.closed = True

    inner = ToolRuntime()
    wrapped = decorator(inner)
    assert wrapped.call_tool("lookup", {}) == ("lookup", {})
    wrapped.close()
    assert waits == [0.05]
    assert inner.closed

    with pytest.raises(ValueError, match="delay-only"):
        DisturbanceSpec("invalid", "1", RuntimeComponent.LOCAL_MCP, DisturbanceKind.DELAY,
                        1, None, 0, delay_ms=1, failure_rate=0.5)


def test_runtime_applies_an_interceptor_only_to_its_declared_component(monkeypatch):
    import ctxbench.runtime.runtime as runtime_module

    seen = []

    class ToolRuntime:
        def list_tools(self): return []
        def call_tool(self, name, arguments): return (name, arguments)
        def close(self): pass

    class MCPRuntime:
        @staticmethod
        def for_local_server(_server): return ToolRuntime()
        @staticmethod
        def from_config(_config): return ToolRuntime()

    class OwnedEngine:
        def __init__(self, factories): self.factories = factories
        def execute(self, request):
            factory = self.factories.get(request.strategy_name)
            if factory:
                runtime = factory()
                seen.append(isinstance(runtime, ToolRuntimeDisturbance))
                runtime.close()
            return AIResult(answer="ok")
        def close(self): pass

    class Engine:
        def copy_with_tool_runtime_factories(self, factories): return OwnedEngine(factories)
        def execute(self, _request): return AIResult(answer="ok")

    class Source:
        def get_context(self, *_args): return type("Payload", (), {"content": "context"})()
        def tool_provider(self, **_kwargs): return object()
        def mcp_server(self, **_kwargs): return object()
        def dataset_instructions(self): return None

    monkeypatch.setattr(runtime_module, "LocalFunctionRuntime", lambda _provider: ToolRuntime())
    monkeypatch.setattr(runtime_module, "MCPRuntime", MCPRuntime)
    disturbance = DisturbanceSpec(
        "local-only", "1", RuntimeComponent.LOCAL_MCP, DisturbanceKind.DELAY,
        1, None, 5, delay_ms=1,
    )
    interceptor = disturbance.decorator(
        component=RuntimeComponent.LOCAL_MCP, sequence=1, candidate_id="candidate-a",
    )
    runtime = ProvisioningRuntime(
        Engine(), Source(), runtime_interceptors={RuntimeComponent.LOCAL_MCP.value: interceptor},
    )

    def execute(strategy, params=None):
        return runtime.execute(RuntimeRequest(
            task="task", task_id="task-1", instance_id="instance-1", provider="mock",
            model_name="mock",
            configuration=ProvisioningConfiguration(
                strategy=strategy, representation="json", surface="surface",
            ),
            surface_spec={"operations": ["lookup"]}, params=params or {},
        ))

    execute("local_function")
    execute("local_mcp")
    execute("remote_mcp", {"mcp_server": {"command": "fixture"}})
    execute("inline")
    assert seen == [False, True, False]
