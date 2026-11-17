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
    DisturbanceKind, DisturbanceSpec, ModelRuntimeDisturbance, RuntimeComponent,
    ToolRuntimeDisturbance, build_runtime_disturbances,
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


def test_model_disturbance_runs_per_call_and_reports_applied_effects():
    from ctxbench.ai.models.base import AIRequest, ModelInput, ModelResponse

    class Model:
        params = {}
        supports_tool_calling = False
        def failure_category(self, _exc): return None
        def generate(self, model_input, request, trace=None):
            return ModelResponse(text="ok")

    waits = []
    spec = DisturbanceSpec("model-delay", "1", RuntimeComponent.MODEL,
                           DisturbanceKind.DELAY, 1, 1, 9, delay_ms=12)
    decorator = spec.decorator(component="model", sequence=1, candidate_id="A", sleeper=waits.append)
    wrapped = decorator(Model())
    response = wrapped.generate(ModelInput(prompt="prompt"), AIRequest(
        question="q", context="", provider_name="mock", model_name="mock", strategy_name="inline",
        context_representation="json"))
    assert response.text == "ok"
    assert waits == [0.012]
    assert wrapped.effect_record("model-delay", "1") == {
        "name": "model-delay", "version": "1", "appliedDelayMs": 12, "injectedFailures": 0,
    }


def test_model_disturbance_failure_is_tagged_at_injection_site():
    from ctxbench.ai.failures import failure_category
    from ctxbench.ai.models.base import AIRequest, ModelInput

    class Model:
        params = {}
        supports_tool_calling = False
        def failure_category(self, _exc): return None
        def generate(self, *_args, **_kwargs): pytest.fail("injected failure should stop before provider call")

    spec = DisturbanceSpec("model-failure", "1", RuntimeComponent.MODEL,
                           DisturbanceKind.FAILURE, 1, None, 9, failure_rate=1)
    wrapped = spec.decorator(component="model", sequence=1, candidate_id="A")(Model())
    with pytest.raises(RuntimeError) as error:
        wrapped.generate(ModelInput(prompt="prompt"), AIRequest(
            question="q", context="", provider_name="mock", model_name="mock", strategy_name="inline",
            context_representation="json"))
    assert failure_category(error.value) == "provider_error"  # as a real provider failure
    assert wrapped.effect_record("model-failure", "1")["injectedFailures"] == 1


def test_model_disturbance_delay_is_in_measured_runtime_and_reported_separately():
    from ctxbench.ai.engine import Engine
    from ctxbench.runtime.disturbances import build_runtime_disturbances

    clock = [0.0]
    definition = {"name": "model-slowdown", "version": "1", "component": "model", "kind": "delay",
                  "delayMs": 25, "firstSequence": 1, "seed": 1}
    interceptors, effects = build_runtime_disturbances(
        [definition], component_sequence=1, candidate_id="A",
        sleeper=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    source = type("Source", (), {
        "get_context": lambda self, *_args: type("Payload", (), {"content": "context"})(),
        "dataset_instructions": lambda self: None,
    })()
    request = RuntimeRequest(
        task="task", task_id="task-1", instance_id="instance-1", provider="mock", model_name="mock",
        configuration=ProvisioningConfiguration(strategy="inline", representation="json", surface="full"),
        surface_spec={}, params={},
    )
    execution = ProvisioningRuntime(Engine(), source, runtime_interceptors=interceptors,
                                   monotonic=lambda: clock[0]).execute(request)
    assert execution.duration_ms == 25
    assert effects() == [{"name": "model-slowdown", "version": "1", "appliedDelayMs": 25,
                          "injectedFailures": 0}]


def test_disturbance_interceptors_are_candidate_sequence_scoped_and_reproducible():
    definition = {"name": "delay", "version": "1", "component": "model", "kind": "delay",
                  "delayMs": 5, "firstSequence": 2, "lastSequence": 3, "seed": 4,
                  "candidates": ["A"]}
    waits = []
    interceptors, effects = build_runtime_disturbances(
        [definition], component_sequence=2, candidate_id="A", sleeper=waits.append)
    assert set(interceptors) == {"model"}
    wrapped = interceptors["model"](type("Model", (), {"generate": lambda self, *args, **kwargs: None})())
    assert effects() == [{"name": "delay", "version": "1", "appliedDelayMs": 0, "injectedFailures": 0}]
    # A second construction with the same seed and scope makes the same seeded failure decision.
    failure = {**definition, "kind": "failure", "delayMs": 0, "failureRate": 0.5}
    decisions = []
    for _ in range(2):
        factories, _ = build_runtime_disturbances([failure], component_sequence=2, candidate_id="A")
        wrapper = factories["model"](type("Model", (), {"generate": lambda self, *args, **kwargs: None})())
        try:
            wrapper.generate(None, None)
            decisions.append(False)
        except RuntimeError:
            decisions.append(True)
    assert decisions[0] == decisions[1]
    assert waits == []
