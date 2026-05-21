from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from ctxbench.ai.engine import Engine
from ctxbench.ai.models.base import AIRequest, ModelAdapter, ModelInput, ModelResponse, ToolCall, ToolResult, ToolSpec
from ctxbench.ai.models.claude import ClaudeModel
from ctxbench.ai.models.gemini import GeminiModel
from ctxbench.ai.models.mock import MockModel
from ctxbench.ai.models.openai import OpenAIModel
from ctxbench.ai.runtime import MCPRuntime
from ctxbench.ai.trace import TraceCollector
from ctxbench.benchmark import executor as executor_module
from ctxbench.benchmark.evaluation import _evaluate_judge, build_evaluation_jobs, evaluate_run_result
from ctxbench.benchmark.executor import execute_runspec
from ctxbench.benchmark.models import (
    EvaluationJudgeInfo,
    EvaluationTrace,
    Experiment,
    ExperimentDataset,
    RunResult,
    RunSpec,
)
from ctxbench.dataset.errors import CapabilityUnavailableError, UnsupportedRepresentationError
from ctxbench.dataset.package import DatasetMetadata
from ctxbench.dataset.payloads import ORACLE_UNAVAILABLE, ContextPayload, EvidencePayload, TaskPayload
from ctxbench.dataset.provider import DatasetProvider
import json


def make_request(**overrides: object) -> AIRequest:
    payload = {
        "question": "How many publications are listed?",
        "context": '{"answers": {"q1": "3"}}',
        "provider_name": "mock",
        "model_name": "mock",
        "strategy_name": "inline",
        "context_format": "json",
        "params": {},
        "metadata": {"taskId": "q1", "lattes_id": "cv-demo", "instanceId": "cv-demo"},
    }
    payload.update(overrides)
    return AIRequest(**payload)


def make_experiment() -> Experiment:
    return Experiment.model_validate(
        {
            "id": "exp-test",
            "output": "outputs",
            "dataset": str((Path.cwd() / "examples" / "datasets" / "lattes").resolve()),
            "scope": {"instances": [], "questions": []},
            "factors": {
                "model": [{"provider": "mock", "name": "mock"}],
                "strategy": ["inline"],
                "format": ["json"],
            },
            "evaluation": {
                "enabled": True,
                "judges": [{"provider": "mock", "model": "mock", "temperature": 0}],
            },
        }
    )


def write_mock_dataset(root: Path) -> ExperimentDataset:
    instance_dir = root / "context" / "cv-demo"
    instance_dir.mkdir(parents=True, exist_ok=True)
    (root / "questions.json").write_text(
        json.dumps(
            {
                "datasetId": "mock-v2",
                "questions": [
                    {
                        "id": "q_year",
                        "question": "In which year did the researcher obtain their PhD?",
                        "tags": ["objective", "simple"],
                        "validation": {"type": "judge"},
                        "contextBlock": ["summary"],
                    },
                    {
                        "id": "q_summary",
                        "question": "Summarize the main research areas for {researcher_name}.",
                        "tags": ["subjective", "simple"],
                        "validation": {"type": "judge"},
                        "contextBlock": ["summary", "research"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "questions.instance.json").write_text(
        json.dumps(
            {
                "datasetId": "mock-v2",
                "instances": [
                    {
                        "instanceId": "cv-demo",
                        "contextBlocks": "context/cv-demo/blocks.json",
                        "questions": [
                            {"id": "q_year"},
                            {"id": "q_summary", "parameters": {"researcher_name": "CV Demo"}},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (instance_dir / "parsed.json").write_text(json.dumps({"answers": {"q_year": 2020}}), encoding="utf-8")
    (instance_dir / "raw.html").write_text("ANSWER[q_year]: 2020\n", encoding="utf-8")
    (instance_dir / "clean.html").write_text("ANSWER[q_year]: 2020\n", encoding="utf-8")
    (instance_dir / "blocks.json").write_text(
        json.dumps({"summary": "Researcher in software engineering.", "research": "Works with distributed systems."}),
        encoding="utf-8",
    )
    return ExperimentDataset(root=str(root.resolve()), id="ctxbench/lattes", version="0.1.0")


def test_dataset_provider_context_blocks_falls_back_to_instance_blocks_file(tmp_path):
    dataset = write_mock_dataset(tmp_path / "dataset")
    payload = json.loads((Path(dataset.root) / "questions.instance.json").read_text(encoding="utf-8"))
    payload["instances"][0].pop("contextBlocks", None)
    (Path(dataset.root) / "questions.instance.json").write_text(json.dumps(payload), encoding="utf-8")

    provider = DatasetProvider.from_dataset(dataset)

    assert provider.get_context_blocks("cv-demo") == {
        "summary": "Researcher in software engineering.",
        "research": "Works with distributed systems.",
    }


class RecordingModel(ModelAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.last_input: ModelInput | None = None
        self.last_request: AIRequest | None = None

    def generate(self, model_input: ModelInput, request: AIRequest, trace: TraceCollector | None = None) -> ModelResponse:
        self.last_input = model_input
        self.last_request = request
        return ModelResponse(
            text="3",
            raw_response={"provider": "recording"},
            input_tokens=11,
            output_tokens=1,
            total_tokens=12,
            cached_input_tokens=4,
            cache_read_input_tokens=4,
            duration_ms=7,
            metadata={"provider": "recording"},
        )


class RecordingJudgeModel(ModelAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.last_input: ModelInput | None = None
        self.last_request: AIRequest | None = None

    def generate(self, model_input: ModelInput, request: AIRequest, trace: TraceCollector | None = None) -> ModelResponse:
        self.last_input = model_input
        self.last_request = request
        return ModelResponse(
            text='{"correctness":{"rating":"meets","justification":"ok"},"completeness":{"rating":"meets","justification":"ok"}}',
            raw_response={"provider": "recording-judge"},
            input_tokens=10,
            output_tokens=10,
            total_tokens=20,
            duration_ms=5,
            metadata={"provider": "recording-judge"},
        )


class ScriptedToolModel(ModelAdapter):
    def __init__(self, responses: list[ModelResponse]) -> None:
        super().__init__()
        self.responses = list(responses)
        self.inputs: list[ModelInput] = []

    def generate(self, model_input: ModelInput, request: AIRequest, trace: TraceCollector | None = None) -> ModelResponse:
        self.inputs.append(model_input)
        return self.responses.pop(0)


class FakeLattesRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(name="get_profile", input_schema={"type": "object"}),
            ToolSpec(name="get_publications", input_schema={"type": "object"}),
        ]

    def call_tool(self, name: str, arguments: dict[str, object]) -> ToolResult:
        self.calls.append((name, arguments))
        if name == "get_profile":
            return ToolResult(name=name, content={"name": "Ada Lovelace"})
        return ToolResult(name=name, content={"items": [{"year": 2024, "title": "Software Engineering Paper"}]})

    def close(self) -> None:
        return None


class FakeDatasetAdapter:
    def __init__(
        self,
        *,
        context_content: object = '{"answers": {"q_year": 2020}}',
        evidence: object | None = None,
        oracle: object = ORACLE_UNAVAILABLE,
        tool_provider: object | None = None,
        unsupported_context: bool = False,
    ) -> None:
        self.context_content = context_content
        self.evidence = evidence if evidence is not None else {
            "summary": {"title": "Summary", "content": "Researcher in software engineering."}
        }
        self.oracle = oracle
        self._tool_provider = tool_provider
        self.unsupported_context = unsupported_context
        self.context_calls: list[tuple[str, str, str]] = []
        self.evidence_calls: list[tuple[str | None, str]] = []
        self.oracle_calls: list[tuple[str | None, str]] = []
        self.tool_provider_calls = 0

    def metadata(self) -> DatasetMetadata:
        return DatasetMetadata(
            name="ctxbench/fake-adapter",
            description="Fake adapter for executor tests.",
            domain="testing",
            intended_uses="Unit tests",
            limitations="None",
            license_url=None,
            citation_url=None,
        )

    def identity(self) -> str:
        return "ctxbench/fake-adapter"

    def version(self) -> str:
        return "0.1.0"

    def origin(self) -> str | None:
        return None

    def list_instance_ids(self) -> list[str]:
        return ["cv-demo"]

    def list_task_ids(self) -> list[str]:
        return ["q_year"]

    def get_task(self, task_id: str) -> TaskPayload:
        return TaskPayload(task_id=task_id, statement="Question?")

    def get_context(self, instance_id: str, task_id: str, representation: str) -> ContextPayload:
        self.context_calls.append((instance_id, task_id, representation))
        if self.unsupported_context:
            raise UnsupportedRepresentationError("unsupported representation")
        return ContextPayload(
            role="context",
            representation=representation,
            content=self.context_content,
        )

    def get_evidence(self, instance_id: str, task_id: str) -> EvidencePayload:
        self.evidence_calls.append((instance_id, task_id))
        return EvidencePayload(
            role="evidence",
            task={"context_blocks": ["summary"]},
            evidence=self.evidence,
        )

    def get_oracle(self, instance_id: str, task_id: str) -> object:
        self.oracle_calls.append((instance_id, task_id))
        return self.oracle

    def capability_report(self) -> object:
        return object()

    def tool_provider(self) -> object | None:
        self.tool_provider_calls += 1
        return self._tool_provider


class FakeRegistry:
    def __init__(self, adapter: FakeDatasetAdapter) -> None:
        self.adapter = adapter
        self.resolved: list[object] = []

    def resolve(self, dataset_ref: object) -> FakeDatasetAdapter:
        self.resolved.append(dataset_ref)
        return self.adapter


def _runspec_for_executor(
    dataset: ExperimentDataset,
    *,
    strategy: str = "inline",
    provider: str = "recording",
    params: dict[str, object] | None = None,
) -> RunSpec:
    return RunSpec.model_validate(
        {
            "trialId": "run-1",
            "experimentId": "exp-1",
            "dataset": dataset.model_dump(mode="json"),
            "taskId": "q_year",
            "question": "In which year did the researcher obtain their PhD?",
            "questionTemplate": "In which year did the researcher obtain their PhD?",
            "instanceId": "cv-demo",
            "provider": provider,
            "model": "recording-model",
            "strategy": strategy,
            "format": "json",
            "repeatIndex": 1,
            "params": params or {},
            "trace": {"enabled": True},
            "metadata": {
                "canonicalId": f"exp-1|q_year|cv-demo|{provider}|recording-model|{strategy}|json|1",
                "taskId": "q_year",
                "instanceId": "cv-demo",
                "provider": provider,
                "modelName": "recording-model",
                "strategy": strategy,
                "format": "json",
                "repeatIndex": 1,
            },
        }
    )


def _run_result_for_evaluation(dataset: ExperimentDataset) -> RunResult:
    return RunResult.model_validate(
        {
            "trialId": "run-1",
            "experimentId": "exp-1",
            "dataset": dataset.model_dump(mode="json"),
            "taskId": "q_year",
            "question": "In which year did the researcher obtain their PhD?",
            "questionTemplate": "In which year did the researcher obtain their PhD?",
            "questionTags": [],
            "validationType": "judge",
            "contextBlock": ["summary"],
            "parameters": {},
            "instanceId": "cv-demo",
            "provider": "mock",
            "model": "mock",
            "strategy": "inline",
            "format": "json",
            "repeatIndex": 1,
            "response": "The PhD was obtained in 2020.",
            "status": "success",
            "timing": {
                "startedAt": "2026-01-01T00:00:00Z",
                "finishedAt": "2026-01-01T00:00:01Z",
                "durationMs": 1000,
            },
            "usage": {},
            "metricsSummary": {},
            "trace": {},
            "metadata": {
                "canonicalId": "exp-1|q_year|cv-demo|mock|mock|inline|json|1",
                "taskId": "q_year",
                "instanceId": "cv-demo",
                "provider": "mock",
                "modelName": "mock",
                "strategy": "inline",
                "format": "json",
                "repeatIndex": 1,
            },
        }
    )


def test_execute_runspec_resolves_adapter_and_uses_get_context_for_inline(monkeypatch, tmp_path):
    dataset = ExperimentDataset(root=str((tmp_path / "dataset").resolve()), id="ctxbench/fake", version="0.1.0")
    adapter = FakeDatasetAdapter(context_content={"answers": {"q_year": 2020}})
    registry = FakeRegistry(adapter)
    monkeypatch.setattr(executor_module, "get_default_registry", lambda: registry)
    engine = Engine()
    model = RecordingModel()
    engine._models["recording"] = model

    result = execute_runspec(_runspec_for_executor(dataset), engine)

    assert result.answer == "3"
    assert registry.resolved == [result.dataset]
    assert adapter.context_calls == [("cv-demo", "q_year", "json")]
    assert model.last_request is not None
    assert model.last_request.context == '{"answers": {"q_year": 2020}}'


def test_execute_runspec_inline_metadata_uses_adapter_boundary_keys(monkeypatch, tmp_path):
    dataset = ExperimentDataset(root=str((tmp_path / "dataset").resolve()), id="ctxbench/fake", version="0.1.0")
    adapter = FakeDatasetAdapter()
    monkeypatch.setattr(executor_module, "get_default_registry", lambda: FakeRegistry(adapter))
    engine = Engine()
    model = RecordingModel()
    engine._models["recording"] = model

    execute_runspec(_runspec_for_executor(dataset), engine)

    assert model.last_request is not None
    metadata = model.last_request.metadata
    assert metadata["instance_id"] == "cv-demo"
    assert metadata["context_representation"] == "json"
    assert metadata["context_obtained"] is True
    assert "context_path" not in metadata
    assert "instance_dir" not in metadata


def test_execute_runspec_inline_unsupported_representation_propagates(monkeypatch, tmp_path):
    dataset = ExperimentDataset(root=str((tmp_path / "dataset").resolve()), id="ctxbench/fake", version="0.1.0")
    adapter = FakeDatasetAdapter(unsupported_context=True)
    monkeypatch.setattr(executor_module, "get_default_registry", lambda: FakeRegistry(adapter))

    with pytest.raises(UnsupportedRepresentationError):
        execute_runspec(_runspec_for_executor(dataset), Engine())


@pytest.mark.parametrize("strategy_name", ["local_function", "local_mcp", "remote_mcp"])
def test_execute_runspec_tool_strategies_use_tool_provider_without_context(monkeypatch, tmp_path, strategy_name):
    dataset = ExperimentDataset(root=str((tmp_path / "dataset").resolve()), id="ctxbench/fake", version="0.1.0")
    service = FakeLattesRuntime()
    adapter = FakeDatasetAdapter(tool_provider=service)
    monkeypatch.setattr(executor_module, "get_default_registry", lambda: FakeRegistry(adapter))
    engine = Engine()
    model = RecordingModel()
    engine._models["recording"] = model

    result = execute_runspec(
        _runspec_for_executor(
            dataset,
            strategy=strategy_name,
            params={"mcp_server": {"server_url": "https://example.test/mcp"}},
        ),
        engine,
    )

    assert result.status == "success"
    assert adapter.context_calls == []
    assert adapter.tool_provider_calls == 1
    assert model.last_request is not None
    assert model.last_request.metadata["context_obtained"] is False
    if strategy_name == "remote_mcp":
        assert model.last_request.metadata["dataset_tool_provider"] is service
        events = result.trace.aiTrace.get("events", [])
        assert any(event["name"] == "strategy.remote_mcp.execute" for event in events)
        assert not any(event["name"] == "strategy.local_mcp.execute" for event in events)


def test_execute_runspec_tool_strategy_missing_provider_raises(monkeypatch, tmp_path):
    dataset = ExperimentDataset(root=str((tmp_path / "dataset").resolve()), id="ctxbench/fake", version="0.1.0")
    adapter = FakeDatasetAdapter(tool_provider=None)
    monkeypatch.setattr(executor_module, "get_default_registry", lambda: FakeRegistry(adapter))

    with pytest.raises(CapabilityUnavailableError):
        execute_runspec(_runspec_for_executor(dataset, strategy="local_function"), Engine())


def test_engine_inline_execution_records_prompt_trace_and_usage():
    engine = Engine()
    model = RecordingModel()
    engine._models["recording"] = model

    result = engine.execute(make_request(provider_name="recording"))

    assert result.answer == "3"
    assert result.usage == {
        "inputTokens": 11,
        "outputTokens": 1,
        "totalTokens": 12,
        "cachedInputTokens": 4,
        "cacheReadInputTokens": 4,
    }


def test_classify_provider_error_treats_taskgroup_as_transient():
    from ctxbench.ai.rate_control import classify_provider_error

    info = classify_provider_error("google", RuntimeError("unhandled errors in a TaskGroup (1 sub-exception)"))

    assert info.kind == "transient"


def test_engine_local_function_uses_resource_tools_and_records_calls():
    runtime = FakeLattesRuntime()
    engine = Engine(tool_runtime_factories={"local_function": lambda: runtime})
    model = ScriptedToolModel(
        [
            ModelResponse(
                requested_tool_calls=[ToolCall(name="get_publications", arguments={"lattes_id": "cv-demo", "start_year": 2020})],
                duration_ms=5,
                input_tokens=10,
                output_tokens=0,
                total_tokens=10,
            ),
            ModelResponse(
                text="Software engineering",
                duration_ms=6,
                input_tokens=4,
                output_tokens=2,
                total_tokens=6,
            ),
        ]
    )
    engine._models["scripted"] = model

    result = engine.execute(make_request(provider_name="scripted", strategy_name="local_function"))

    assert result.answer == "Software engineering"
    assert runtime.calls == [("get_publications", {"lattes_id": "cv-demo", "start_year": 2020})]
    assert "Researcher Lattes ID:" in model.inputs[0].prompt
    assert result.trace["metrics"]["mcpToolCalls"] == 1


def test_engine_resolves_remote_mcp_and_keeps_local_mcp_distinct():
    engine = Engine(tool_runtime_factories={"local_mcp": lambda: FakeLattesRuntime()})

    remote_strategy, remote_runtime = engine._resolve_strategy("remote_mcp")
    local_strategy, local_runtime = engine._resolve_strategy("local_mcp")

    assert type(remote_strategy).__name__ == "MCPStrategy"
    assert remote_runtime is None
    assert type(local_strategy).__name__ == "LocalMCPStrategy"
    assert local_runtime is not None
    local_runtime.close()


def test_trace_collector_recognizes_remote_mcp_strategy_span():
    trace = TraceCollector()

    with trace.span("strategy.remote_mcp.execute", "strategy.remote_mcp.execute"):
        pass

    serialized = trace.to_trace().model_dump(mode="json")

    assert serialized["metrics"]["strategyDurationMs"] is not None
    assert any(event["name"] == "strategy.remote_mcp.execute" for event in serialized["events"])
    assert not any(event["name"] == "strategy.mcp.execute" for event in serialized["events"])


def test_engine_rejects_bare_mcp_strategy_name():
    engine = Engine()

    with pytest.raises(ValueError, match="Unknown strategy: mcp"):
        engine._resolve_strategy("mcp")


def test_experiment_validation_rejects_bare_mcp_strategy_factor():
    with pytest.raises(ValueError, match="unknown strategy: mcp"):
        Experiment.model_validate(
            {
                "id": "exp-test",
                "output": "outputs",
                "dataset": "/tmp/dataset",
                "scope": {"instances": [], "questions": []},
                "factors": {
                    "model": [{"provider": "mock", "name": "mock"}],
                    "strategy": ["mcp"],
                    "format": ["json"],
                },
            }
        )


def test_runspec_model_validate_rejects_bare_mcp_strategy_in_public_record():
    with pytest.raises(ValueError, match="unknown strategy: mcp"):
        RunSpec.model_validate(
            {
                "trialId": "trial-1",
                "experimentId": "exp-1",
                "taskId": "q_year",
                "question": "In which year did the researcher obtain their PhD?",
                "dataset": {"root": "/tmp/dataset"},
                "instanceId": "cv-demo",
                "provider": "mock",
                "model": "mock",
                "modelId": "mock",
                "strategy": "mcp",
                "format": "json",
                "params": {},
                "repeatIndex": 1,
                "trace": {"enabled": False, "writeFiles": True, "save_raw_response": False, "save_tool_calls": False, "save_usage": False, "save_errors": False},
                "artifacts": {"writeJsonl": True, "writeIndividualJson": False},
                "metadata": {
                    "canonicalId": "exp-1|q_year|cv-demo|mock|mock|mcp|json|1",
                    "taskId": "q_year",
                    "instanceId": "cv-demo",
                    "provider": "mock",
                    "modelId": "mock",
                    "modelName": "mock",
                    "strategy": "mcp",
                    "format": "json",
                    "repeatIndex": 1,
                },
            }
        )


def test_runresult_model_validate_rejects_bare_mcp_strategy_in_public_record():
    with pytest.raises(ValueError, match="unknown strategy: mcp"):
        RunResult.model_validate(
            {
                "trialId": "trial-1",
                "experimentId": "exp-1",
                "taskId": "q_year",
                "question": "In which year did the researcher obtain their PhD?",
                "dataset": {"root": "/tmp/dataset"},
                "instanceId": "cv-demo",
                "provider": "mock",
                "model": "mock",
                "modelId": "mock",
                "strategy": "mcp",
                "format": "json",
                "repeatIndex": 1,
                "status": "success",
                "response": "2018",
                "timing": {"startedAt": "2026-01-01T00:00:00Z", "finishedAt": "2026-01-01T00:00:01Z", "durationMs": 1000},
                "usage": {},
                "metricsSummary": {},
                "metadata": {
                    "canonicalId": "exp-1|q_year|cv-demo|mock|mock|mcp|json|1",
                    "taskId": "q_year",
                    "instanceId": "cv-demo",
                    "provider": "mock",
                    "modelId": "mock",
                    "modelName": "mock",
                    "strategy": "mcp",
                    "format": "json",
                    "repeatIndex": 1,
                },
            }
        )


def test_evaluate_judge_persists_rating_and_justification(monkeypatch):
    from ctxbench.benchmark import evaluation as evaluation_module

    def fake_judge_request(**kwargs):
        config = kwargs["config"]
        return (
            {
                "correctness": {"rating": "meets", "justification": f"Consistent according to {config.model}."},
                "completeness": {"rating": "partially meets", "justification": f"Partial according to {config.model}."},
            },
            EvaluationJudgeInfo(used=True, role="judge", provider=config.provider, model=config.model),
            EvaluationTrace(),
        )

    monkeypatch.setattr(evaluation_module, "_judge_request", fake_judge_request)

    details, judge_info, _ = _evaluate_judge(
        result=type("R", (), {"answer": "Answer", "runId": "run-1", "experimentId": "exp-1", "instanceId": "cv-demo", "questionId": "q_summary"})(),
        question_text="Question?",
        context_payload={"summary": "Ground truth answer."},
        judges=make_experiment().evaluation.judges,
        engine=Engine(),
    )

    assert details["outcome"]["correctness"]["rating"] == "meets"
    assert details["outcome"]["completeness"]["rating"] == "partial"
    assert details["outcome"]["correctness"]["agreement"] is True
    assert details["outcome"]["completeness"]["agreement"] is True
    assert len(details["judges"]) == 1
    assert judge_info.used is True


def test_evaluate_judge_aggregates_multiple_judges(monkeypatch):
    from ctxbench.benchmark import evaluation as evaluation_module

    experiment = Experiment.model_validate(
        {
            "id": "exp-test",
            "output": "outputs",
            "dataset": str((Path.cwd() / "datasets" / "lattes").resolve()),
            "scope": {"instances": [], "questions": []},
            "factors": {
                "model": [{"provider": "mock", "name": "mock"}],
                "strategy": ["inline"],
                "format": ["json"],
            },
            "evaluation": {
                "enabled": True,
                "judges": [
                    {"provider": "mock", "model": "judge-a", "temperature": 0},
                    {"provider": "mock", "model": "judge-b", "temperature": 0},
                ],
            },
        }
    )

    def fake_judge_request(**kwargs):
        config = kwargs["config"]
        if config.model == "judge-a":
            return (
                {
                    "correctness": {"rating": "meets", "justification": "A says correct."},
                    "completeness": {"rating": "partially meets", "justification": "A says partial."},
                },
                EvaluationJudgeInfo(used=True, role="judge", provider=config.provider, model=config.model),
                EvaluationTrace(),
            )
        return (
            {
                "correctness": {"rating": "does not meet", "justification": "B says incorrect."},
                "completeness": {"rating": "partially meets", "justification": "B says partial."},
            },
            EvaluationJudgeInfo(used=True, role="judge", provider=config.provider, model=config.model),
            EvaluationTrace(),
        )

    monkeypatch.setattr(evaluation_module, "_judge_request", fake_judge_request)

    details, judge_info, _ = _evaluate_judge(
        result=type("R", (), {"answer": "Answer", "runId": "run-1", "experimentId": "exp-1", "instanceId": "cv-demo", "questionId": "q_summary"})(),
        question_text="Question?",
        context_payload={"summary": "Ground truth answer."},
        judges=experiment.evaluation.judges,
        engine=Engine(),
    )

    assert details["outcome"]["correctness"]["rating"] == "meets"
    assert details["outcome"]["correctness"]["agreement"] is False
    assert details["outcome"]["completeness"]["rating"] == "partial"
    assert details["outcome"]["completeness"]["agreement"] is True
    assert len(details["judges"]) == 2
    assert judge_info.used is True


def test_judge_request_injects_structured_output_schema():
    from ctxbench.benchmark.evaluation import _judge_request

    engine = Engine()
    model = RecordingJudgeModel()
    engine._models["openai"] = model

    payload, judge_info, _ = _judge_request(
        config=type(
            "Cfg",
            (),
            {
                "provider": "openai",
                "model": "recording_judge",
                "temperature": 0,
                "params": {},
            },
        )(),
        prompt="Judge this answer.",
        answer_text="The candidate answer.",
        run_id="run-1",
        exp_id="exp-1",
        instance_id="cv-demo",
        question_id="q_summary",
        question_text="Question?",
        curriculum_context='{"summary":"Research summary"}',
        engine=engine,
    )

    assert payload is not None
    assert judge_info.used is True
    assert model.last_request is not None
    assert model.last_request.params["structured_output"]["schema"]["type"] == "object"
    assert model.last_request.params["structured_output"]["schema"]["required"] == ["correctness", "completeness"]
    assert model.last_request.params["prompt_cache_key"].startswith("jud:ctx:")


def test_execute_runspec_persists_metrics_summary_with_nulls_for_remote_mcp(tmp_path):
    dataset = write_mock_dataset(tmp_path / "dataset")
    runspec = RunSpec.model_validate(
        {
            "trialId": "run-1",
            "experimentId": "exp-1",
            "dataset": dataset.model_dump(mode="json"),
            "taskId": "q_year",
            "instanceId": "cv-demo",
            "provider": "mock",
            "model": "mock",
            "strategy": "remote_mcp",
            "format": "json",
            "repeatIndex": 1,
            "params": {"mcp_server": {"server_url": "https://example.test/mcp"}},
            "trace": {"enabled": True},
            "metadata": {
                "canonicalId": "exp-1|q_year|cv-demo|mock|mock|remote_mcp|json|1",
                "taskId": "q_year",
                "instanceId": "cv-demo",
                "provider": "mock",
                "modelName": "mock",
                "strategy": "remote_mcp",
                "format": "json",
                "repeatIndex": 1,
            },
        }
    )

    result = execute_runspec(runspec, Engine())

    assert isinstance(result.answer, str)
    assert result.metricsSummary["toolCalls"] == 0
    assert result.metricsSummary["functionCalls"] == 0
    assert result.metricsSummary["inputTokens"] is not None
    events = result.trace.aiTrace.get("events", [])
    assert any(event["name"] == "strategy.remote_mcp.execute" for event in events)
    assert not any(event["name"] == "strategy.mcp.execute" for event in events)
    assert result.trace.aiTrace.get("metrics", {}).get("strategyDurationMs") is not None


def test_execute_runspec_injects_openai_inline_prompt_cache_key(tmp_path):
    dataset = write_mock_dataset(tmp_path / "dataset")
    runspec = RunSpec.model_validate(
        {
            "trialId": "run-1",
            "experimentId": "exp-1",
            "dataset": dataset.model_dump(mode="json"),
            "taskId": "q_year",
            "question": "In which year did the researcher obtain their PhD?",
            "questionTemplate": "In which year did the researcher obtain their PhD?",
            "instanceId": "cv-demo",
            "provider": "openai",
            "model": "gpt-5.4-mini",
            "strategy": "inline",
            "format": "html",
            "repeatIndex": 1,
            "params": {},
            "metadata": {
                "canonicalId": "exp-1|q_year|cv-demo|openai|gpt-5.4-mini|inline|html|1",
                "taskId": "q_year",
                "instanceId": "cv-demo",
                "provider": "openai",
                "modelName": "gpt-5.4-mini",
                "strategy": "inline",
                "format": "html",
                "repeatIndex": 1,
            },
        }
    )
    engine = Engine()
    model = RecordingModel()
    engine._models["openai"] = model

    execute_runspec(runspec, engine)

    assert model.last_request is not None
    cache_key = model.last_request.params["prompt_cache_key"]
    assert cache_key.startswith("inl:html:")
    assert len(cache_key) <= 64


def test_openai_model_build_payload_includes_prompt_cache_fields():
    model = OpenAIModel()
    request = AIRequest(
        question="Question?",
        context="Context",
        provider_name="openai",
        model_name="gpt-5.4-mini",
        strategy_name="inline",
        context_format="text",
        params={
            "prompt_cache_key": "inl:html:abc123",
            "prompt_cache_retention": "24h",
        },
        metadata={},
    )
    model_input = ModelInput(system_instruction="System", prompt="Prompt")

    payload = model._build_payload(model_input, request)

    assert payload["prompt_cache_key"] == "inl:html:abc123"
    assert payload["prompt_cache_retention"] == "24h"


def test_openai_model_request_metadata_uses_target_public_keys():
    model = OpenAIModel()
    request = AIRequest(
        question="Question?",
        context="Context",
        provider_name="openai",
        model_name="gpt-5.4-mini",
        strategy_name="inline",
        context_format="text",
        params={},
        metadata={
            "trialId": "trial-1",
            "experimentId": "exp-1",
            "taskId": "q_summary",
            "phase": "execution",
        },
    )

    metadata = model._request_metadata(request)

    assert metadata == {
        "trialId": "trial-1",
        "experimentId": "exp-1",
        "taskId": "q_summary",
        "phase": "execution",
    }


def test_claude_model_request_metadata_uses_target_public_keys():
    model = ClaudeModel()
    request = AIRequest(
        question="Question?",
        context="Context",
        provider_name="anthropic",
        model_name="claude-sonnet",
        strategy_name="inline",
        context_format="text",
        params={},
        metadata={
            "trialId": "trial-1",
            "experimentId": "exp-1",
            "taskId": "q_summary",
            "phase": "evaluation",
        },
    )

    metadata = model._request_metadata(request)

    assert metadata == {
        "user_id": "trialId=trial-1;experimentId=exp-1;taskId=q_summary;phase=evaluation"
    }


def test_openai_native_mcp_tools_accept_remote_mcp_and_reject_mcp():
    model = OpenAIModel()
    remote_request = AIRequest(
        question="Question?",
        context="Context",
        provider_name="openai",
        model_name="gpt-5.4-mini",
        strategy_name="remote_mcp",
        context_format="text",
        params={"mcp_server": {"server_url": "https://example.test/mcp"}},
        metadata={},
    )

    tools = model._build_native_mcp_tools(remote_request)

    assert tools[0]["type"] == "mcp"
    assert tools[0]["server_label"] == "ctxbench-lattes"

    legacy_request = remote_request.model_copy(update={"strategy_name": "mcp"})
    with pytest.raises(ValueError, match="unknown strategy: mcp"):
        model._build_native_mcp_tools(legacy_request)


def test_claude_native_mcp_servers_accept_remote_mcp_and_reject_mcp():
    model = ClaudeModel()
    remote_request = AIRequest(
        question="Question?",
        context="Context",
        provider_name="anthropic",
        model_name="claude-sonnet",
        strategy_name="remote_mcp",
        context_format="text",
        params={"mcp_server": {"server_url": "https://example.test/mcp"}},
        metadata={},
    )

    servers = model._build_native_mcp_servers(remote_request)

    assert servers[0]["name"] == "ctxbench-lattes"
    assert servers[0]["url"] == "https://example.test/mcp"

    legacy_request = remote_request.model_copy(update={"strategy_name": "mcp"})
    with pytest.raises(ValueError, match="unknown strategy: mcp"):
        model._build_native_mcp_servers(legacy_request)


def test_gemini_native_mcp_tool_accepts_remote_mcp_and_rejects_mcp():
    model = GeminiModel()
    remote_request = AIRequest(
        question="Question?",
        context="Context",
        provider_name="google",
        model_name="gemini-2.5-flash",
        strategy_name="remote_mcp",
        context_format="text",
        params={"mcp_server": {"server_url": "https://example.test/mcp"}},
        metadata={},
    )

    tool = model._build_native_mcp_tool(remote_request)
    tool_payload = tool.model_dump(mode="json") if hasattr(tool, "model_dump") else tool

    assert tool_payload["mcp_servers"][0]["name"] == "ctxbench-lattes"
    assert tool_payload["mcp_servers"][0]["streamable_http_transport"]["url"] == "https://example.test/mcp"

    with pytest.raises(ValueError, match="unknown strategy: mcp"):
        model.generate(
            ModelInput(system_instruction="System", prompt="Prompt"),
            remote_request.model_copy(update={"strategy_name": "mcp"}),
        )


def test_gemini_generate_uses_native_mcp_path_for_remote_mcp(monkeypatch):
    model = GeminiModel()
    request = AIRequest(
        question="Question?",
        context="Context",
        provider_name="google",
        model_name="gemini-2.5-flash",
        strategy_name="remote_mcp",
        context_format="text",
        params={"mcp_server": {"server_url": "https://example.test/mcp"}},
        metadata={},
    )
    expected = ModelResponse(text="ok")
    called: dict[str, object] = {}

    async def fake_generate_with_native_mcp(model_input, incoming_request):
        called["strategy"] = incoming_request.strategy_name
        return expected

    def fake_run_async(coro):
        called["used"] = True
        try:
            return coro.send(None)
        except StopIteration as exc:
            return exc.value

    monkeypatch.setattr(model, "_generate_with_native_mcp", fake_generate_with_native_mcp)
    monkeypatch.setattr(model, "_run_async", fake_run_async)

    result = model.generate(ModelInput(system_instruction="System", prompt="Prompt"), request)

    assert called == {"used": True, "strategy": "remote_mcp"}
    assert result.text == "ok"


def test_mock_model_uses_task_metadata_lookup():
    model = MockModel()
    request = AIRequest(
        question="Question?",
        context='{"answers": {"q_task": "42"}}',
        provider_name="mock",
        model_name="mock",
        strategy_name="inline",
        context_format="json",
        params={},
        metadata={"taskId": "q_task"},
    )

    response = model.generate(ModelInput(system_instruction="System", prompt="Prompt"), request)

    assert response.text == "42"


def test_build_evaluation_jobs_resolves_adapter_and_uses_evidence(monkeypatch, tmp_path):
    from ctxbench.benchmark import evaluation as evaluation_module

    dataset = ExperimentDataset(root=str((tmp_path / "dataset").resolve()), id="ctxbench/fake", version="0.1.0")
    adapter = FakeDatasetAdapter()
    registry = FakeRegistry(adapter)
    monkeypatch.setattr(evaluation_module, "get_default_registry", lambda: registry)

    jobs = build_evaluation_jobs(
        [_run_result_for_evaluation(dataset)],
        judges=[make_experiment().evaluation.judges[0]],
    )

    assert len(jobs) == 1
    assert registry.resolved == [jobs[0].result.dataset]
    assert adapter.evidence_calls == [("cv-demo", "q_year")]
    assert adapter.oracle_calls == [("cv-demo", "q_year")]
    assert jobs[0].context_payload == {
        "summary": {"title": "Summary", "content": "Researcher in software engineering."}
    }
    assert "Researcher in software engineering." in jobs[0].prompt


def test_evaluate_run_result_records_unavailable_oracle_without_using_it_in_prompt(monkeypatch, tmp_path):
    from ctxbench.benchmark import evaluation as evaluation_module

    dataset = ExperimentDataset(root=str((tmp_path / "dataset").resolve()), id="ctxbench/fake", version="0.1.0")
    adapter = FakeDatasetAdapter(oracle=ORACLE_UNAVAILABLE)
    seen: dict[str, object] = {}

    def fake_judge_request(**kwargs):
        seen.update(kwargs)
        return (
            {
                "correctness": {"rating": "meets", "justification": "supported"},
                "completeness": {"rating": "meets", "justification": "complete"},
            },
            EvaluationJudgeInfo(used=True, role="judge", provider="mock", model="mock"),
            EvaluationTrace(aiTrace={"events": []}),
        )

    monkeypatch.setattr(evaluation_module, "_judge_request", fake_judge_request)

    evaluated = evaluate_run_result(
        _run_result_for_evaluation(dataset),
        adapter,
        judges=[make_experiment().evaluation.judges[0]],
        engine=Engine(),
    )

    assert evaluated is not None
    item = evaluated.items[0]
    assert adapter.evidence_calls == [("cv-demo", "q_year")]
    assert adapter.oracle_calls == [("cv-demo", "q_year")]
    assert item.details["evidence_obtained"] is True
    assert item.details["oracle_available"] is False
    assert item.details["oracle_used"] is False
    assert item.evaluationTrace.aiTrace["metadata"]["oracle_used"] is False
    assert "oracle" not in seen
    assert "oracle" not in str(seen["prompt"]).lower()
    assert "oracle" not in str(seen["curriculum_context"]).lower()


def test_evaluate_run_result_records_available_oracle_but_keeps_it_out_of_prompt(monkeypatch, tmp_path):
    from ctxbench.benchmark import evaluation as evaluation_module

    dataset = ExperimentDataset(root=str((tmp_path / "dataset").resolve()), id="ctxbench/fake", version="0.1.0")
    adapter = FakeDatasetAdapter(oracle={"answer": "SECRET_ORACLE_VALUE"})
    seen: dict[str, object] = {}

    def fake_judge_request(**kwargs):
        seen.update(kwargs)
        return (
            {
                "correctness": {"rating": "meets", "justification": "supported"},
                "completeness": {"rating": "meets", "justification": "complete"},
            },
            EvaluationJudgeInfo(used=True, role="judge", provider="mock", model="mock"),
            EvaluationTrace(),
        )

    monkeypatch.setattr(evaluation_module, "_judge_request", fake_judge_request)

    evaluated = evaluate_run_result(
        _run_result_for_evaluation(dataset),
        adapter,
        judges=[make_experiment().evaluation.judges[0]],
        engine=Engine(),
    )

    assert evaluated is not None
    item = evaluated.items[0]
    assert item.details["oracle_available"] is True
    assert item.details["oracle_used"] is False
    assert item.evaluationTrace.aiTrace["metadata"]["oracle_available"] is True
    assert "SECRET_ORACLE_VALUE" not in str(seen["prompt"])
    assert "SECRET_ORACLE_VALUE" not in str(seen["curriculum_context"])


def test_mcp_runtime_defaults_public_server_label_to_ctxbench():
    runtime = MCPRuntime(transport="streamable_http", server_url="https://example.test/mcp")

    metadata = runtime._session_metadata()

    assert metadata["serverLabel"] == "ctxbench-lattes"
    assert metadata["serverUrl"] == "https://example.test/mcp"


def test_evaluate_run_result_skips_when_context_block_missing(tmp_path):
    # Add a question whose contextBlock references a block that doesn't exist in blocks.json
    dataset_root = tmp_path / "dataset"
    dataset = write_mock_dataset(dataset_root)
    questions_path = dataset_root / "questions.json"
    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    questions["questions"].append({
        "id": "q_missing",
        "question": "What is the missing answer?",
        "tags": [],
        "validation": {"type": "judge"},
        "contextBlock": ["nonexistent_block"],
    })
    questions_path.write_text(json.dumps(questions), encoding="utf-8")
    instances_path = dataset_root / "questions.instance.json"
    instances = json.loads(instances_path.read_text(encoding="utf-8"))
    instances["instances"][0]["questions"].append({"id": "q_missing"})
    instances_path.write_text(json.dumps(instances), encoding="utf-8")

    provider = DatasetProvider.from_dataset(dataset)
    events: list[tuple[str, str, dict[str, object]]] = []
    result = RunResult.model_validate(
        {
            "trialId": "run-skip",
            "experimentId": "exp-1",
            "dataset": dataset.model_dump(mode="json"),
            "taskId": "q_missing",
            "question": "What is the missing answer?",
            "questionTemplate": "What is the missing answer?",
            "questionTags": [],
            "validationType": "judge",
            "contextBlock": [],
            "parameters": {},
            "instanceId": "cv-demo",
            "provider": "mock",
            "model": "mock",
            "strategy": "inline",
            "format": "json",
            "repeatIndex": 1,
            "response": "unknown",
            "status": "success",
            "timing": {
                "startedAt": "2026-01-01T00:00:00Z",
                "finishedAt": "2026-01-01T00:00:01Z",
                "durationMs": 1000,
            },
            "usage": {},
            "metricsSummary": {},
            "trace": {},
            "metadata": {
                "canonicalId": "exp-1|q_missing|cv-demo|mock|mock|inline|json|1",
                "taskId": "q_missing",
                "instanceId": "cv-demo",
                "provider": "mock",
                "modelName": "mock",
                "strategy": "inline",
                "format": "json",
                "repeatIndex": 1,
            },
        }
    )

    evaluated = evaluate_run_result(
        result,
        provider,
        judges=[make_experiment().evaluation.judges[0]],
        engine=Engine(),
        event_logger=lambda label, message, fields: events.append((label, message, fields)),
    )

    assert evaluated is not None
    item = evaluated.items[0]
    assert item.status == "skipped"
    assert "nonexistent_block" in item.details.get("error", "")
    artifact = item.to_persisted_artifact()
    assert artifact["trialId"] == "run-skip"
    assert artifact["taskId"] == "q_missing"
    assert artifact["status"] == "skipped"
    assert artifact["judgeCount"] == 0
    assert any(label == "SKIP" and fields.get("questionId") == "q_missing" for label, _message, fields in events)


def test_openai_model_extracts_cache_metadata():
    class UsageDetails:
        def __init__(self, cached_tokens: int) -> None:
            self.cached_tokens = cached_tokens

    class Usage:
        def __init__(self) -> None:
            self.input_tokens = 100
            self.output_tokens = 10
            self.total_tokens = 110
            self.input_tokens_details = UsageDetails(cached_tokens=64)
            self.prompt_tokens_details = [{"type": "cached_tokens", "token_count": 64}]
            self.cache_tokens_details = {"cached_tokens": 64}
            self.cached_content_token_count = 64

    class Response:
        def __init__(self) -> None:
            self.usage = Usage()
            self.output_text = "ok"
            self.output = []

    model = OpenAIModel()
    metadata = model._extract_cache_metadata(Response())

    assert metadata == {
        "cache": {
            "input_tokens_details": {"cached_tokens": 64},
            "prompt_tokens_details": [{"type": "cached_tokens", "token_count": 64}],
            "cache_tokens_details": {"cached_tokens": 64},
            "cached_content_token_count": 64,
        }
    }


def test_openai_model_extracts_cached_input_tokens():
    class UsageDetails:
        def __init__(self, cached_tokens: int) -> None:
            self.cached_tokens = cached_tokens

    class Usage:
        def __init__(self) -> None:
            self.input_tokens_details = UsageDetails(cached_tokens=64)

    class Response:
        def __init__(self) -> None:
            self.usage = Usage()

    assert OpenAIModel()._extract_cached_input_tokens(Response()) == 64


def test_claude_model_extracts_cache_usage():
    class Usage:
        def __init__(self) -> None:
            self.cache_read_input_tokens = 100
            self.cache_creation_input_tokens = 25

    class Response:
        def __init__(self) -> None:
            self.usage = Usage()

    assert ClaudeModel()._extract_cache_usage(Response()) == (100, 25)


def test_gemini_model_extracts_cached_input_tokens():
    class UsageMetadata:
        def __init__(self) -> None:
            self.cached_content_token_count = 42

    class Response:
        def __init__(self) -> None:
            self.usage_metadata = UsageMetadata()

    assert GeminiModel()._extract_cached_input_tokens(Response()) == 42
