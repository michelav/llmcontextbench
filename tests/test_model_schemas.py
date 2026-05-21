from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctxbench.benchmark.models import (
    DatasetProvenance,
    EvaluationItemResult,
    EvaluationRunResult,
    EvaluationRunSummary,
    EvaluationTrace,
    ExperimentDataset,
    ExperimentScope,
    RunMetadata,
    RunResult,
    RunSpec,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def make_dataset() -> ExperimentDataset:
    return ExperimentDataset(root="/tmp/dataset")


def test_experiment_scope_uses_tasks_with_questions_compatibility_alias():
    scoped = ExperimentScope.model_validate({"instances": ["cv-demo"], "tasks": ["q_year"]})
    legacy = ExperimentScope.model_validate({"instances": ["cv-demo"], "questions": ["q_year"]})

    assert scoped.tasks == ["q_year"]
    assert scoped.questions == ["q_year"]
    assert legacy.tasks == ["q_year"]
    assert legacy.questions == ["q_year"]


def make_metadata() -> RunMetadata:
    return RunMetadata(
        canonicalId="exp-1|q_year|cv-demo|mock|mock|inline|json|1",
        questionId="q_year",
        instanceId="cv-demo",
        provider="mock",
        modelId="mock",
        modelName="mock",
        strategy="inline",
        format="json",
        repeatIndex=1,
        questionTags=["objective"],
        validationType="judge",
        parameters={},
    )


def make_runspec_payload() -> dict[str, object]:
    return {
        "trialId": "trial-1",
        "experimentId": "exp-1",
        "taskId": "q_year",
        "question": "In which year did the researcher obtain their PhD?",
        "questionTemplate": "In which year did the researcher obtain their PhD?",
        "dataset": {"root": "/tmp/dataset"},
        "instanceId": "cv-demo",
        "model": "mock",
        "modelId": "mock",
        "provider": "mock",
        "strategy": "inline",
        "format": "json",
        "params": {},
        "repeatIndex": 1,
        "outputRoot": "/tmp/output",
        "evaluationEnabled": False,
        "trace": {"enabled": False, "writeFiles": True, "save_raw_response": False, "save_tool_calls": False, "save_usage": False, "save_errors": False},
        "artifacts": {"writeJsonl": True, "writeIndividualJson": False},
        "questionTags": ["objective"],
        "validationType": "judge",
        "contextBlock": ["summary"],
        "parameters": {},
        "metadata": {
            "canonicalId": "exp-1|q_year|cv-demo|mock|mock|inline|json|1",
            "taskId": "q_year",
            "instanceId": "cv-demo",
            "provider": "mock",
            "modelId": "mock",
            "modelName": "mock",
            "strategy": "inline",
            "format": "json",
            "repeatIndex": 1,
            "questionTags": ["objective"],
            "validationType": "judge",
            "parameters": {},
        },
    }


def make_runresult_payload() -> dict[str, object]:
    return {
        "trialId": "trial-1",
        "experimentId": "exp-1",
        "taskId": "q_year",
        "question": "In which year did the researcher obtain their PhD?",
        "questionTemplate": "In which year did the researcher obtain their PhD?",
        "dataset": {"root": "/tmp/dataset"},
        "instanceId": "cv-demo",
        "provider": "mock",
        "modelId": "mock",
        "model": "mock",
        "strategy": "inline",
        "format": "json",
        "repeatIndex": 1,
        "outputRoot": "/tmp/output",
        "status": "success",
        "response": "2018",
        "errorMessage": None,
        "timing": {"startedAt": "2026-01-01T00:00:00Z", "finishedAt": "2026-01-01T00:00:01Z", "durationMs": 1000},
        "usage": {},
        "metricsSummary": {},
        "traceRef": None,
        "questionTags": ["objective"],
        "validationType": "judge",
        "contextBlock": ["summary"],
        "parameters": {},
        "metadata": {
            "canonicalId": "exp-1|q_year|cv-demo|mock|mock|inline|json|1",
            "taskId": "q_year",
            "instanceId": "cv-demo",
            "provider": "mock",
            "modelId": "mock",
            "modelName": "mock",
            "strategy": "inline",
            "format": "json",
            "repeatIndex": 1,
            "questionTags": ["objective"],
            "validationType": "judge",
            "parameters": {},
        },
    }


def test_runspec_model_validate_accepts_target_public_fields():
    runspec = RunSpec.model_validate(make_runspec_payload())

    assert runspec.runId == "trial-1"
    assert runspec.questionId == "q_year"
    assert runspec.metadata.questionId == "q_year"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runId", "trial-1"),
        ("questionId", "q_year"),
    ],
)
def test_runspec_model_validate_rejects_legacy_public_fields(field: str, value: str):
    payload = make_runspec_payload()
    payload.pop("trialId", None)
    payload.pop("taskId", None)
    payload[field] = value

    with pytest.raises(ValueError):
        RunSpec.model_validate(payload)


def test_runspec_model_validate_rejects_legacy_metadata_field():
    payload = make_runspec_payload()
    payload["metadata"] = dict(payload["metadata"])
    payload["metadata"].pop("taskId", None)
    payload["metadata"]["questionId"] = "q_year"

    with pytest.raises(ValueError):
        RunSpec.model_validate(payload)


def test_runresult_model_validate_accepts_target_public_fields():
    result = RunResult.model_validate(make_runresult_payload())

    assert result.runId == "trial-1"
    assert result.questionId == "q_year"
    assert result.answer == "2018"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runId", "trial-1"),
        ("questionId", "q_year"),
        ("answer", "2018"),
    ],
)
def test_runresult_model_validate_rejects_legacy_public_fields(field: str, value: str):
    payload = make_runresult_payload()
    payload.pop("trialId", None)
    payload.pop("taskId", None)
    payload.pop("response", None)
    payload[field] = value

    with pytest.raises(ValueError):
        RunResult.model_validate(payload)


def test_runresult_model_validate_rejects_legacy_metadata_field():
    payload = make_runresult_payload()
    payload["metadata"] = dict(payload["metadata"])
    payload["metadata"].pop("taskId", None)
    payload["metadata"]["questionId"] = "q_year"

    with pytest.raises(ValueError):
        RunResult.model_validate(payload)


def test_evaluation_item_serializers_use_trial_and_task_ids():
    item = EvaluationItemResult(
        experimentId="exp-1",
        runId="trial-1",
        dataset=DatasetProvenance(
            id="ctxbench/fake",
            version="0.1.0",
            origin="/tmp/dataset",
            materialized_path="/tmp/dataset",
        ),
        questionId="q_year",
        instanceId="cv-demo",
        question="In which year did the researcher obtain their PhD?",
        evaluationMode="judge",
        executionStrategy="inline",
        details={
            "judges": [
                {
                    "judgeId": "judge-1",
                    "provider": "mock",
                    "model": "mock",
                    "correctness": {"rating": "meets", "justification": "ok"},
                    "completeness": {"rating": "meets", "justification": "ok"},
                    "inputTokens": 1,
                    "outputTokens": 1,
                    "durationMs": 1,
                }
            ]
        },
        evaluationTrace=EvaluationTrace(),
    )

    artifact = item.to_persisted_artifact()
    votes = item.to_judge_votes()

    assert artifact["trialId"] == "trial-1"
    assert artifact["taskId"] == "q_year"
    assert "runId" not in artifact
    assert "questionId" not in artifact
    assert votes[0]["trialId"] == "trial-1"
    assert votes[0]["taskId"] == "q_year"
    assert "runId" not in votes[0]
    assert "questionId" not in votes[0]


def test_evaluation_run_result_model_validate_rejects_legacy_public_fields():
    metadata = {
        "canonicalId": "trial-1",
        "taskId": "q_year",
        "instanceId": "cv-demo",
        "provider": "mock",
        "modelId": "mock",
        "modelName": "mock",
        "strategy": "inline",
        "format": "json",
        "repeatIndex": 1,
    }

    with pytest.raises(ValueError):
        EvaluationRunResult.model_validate(
            {
                "runId": "trial-1",
                "questionId": "q_year",
                "experimentId": "exp-1",
                "items": [],
                "summary": EvaluationRunSummary(),
                "metadata": metadata,
            }
        )


def test_schema_public_identifiers_use_ctxbench_names():
    runspec_schema = json.loads((REPO_ROOT / "src/schemas/runspec.schema.json").read_text(encoding="utf-8"))
    plan_schema = json.loads((REPO_ROOT / "src/schemas/plan.schema.json").read_text(encoding="utf-8"))

    assert runspec_schema["$id"] == "https://ctxbench-benchmark.org/schemas/runspec.schema.json"
    assert runspec_schema["title"] == "CTXBench RunSpec"
    assert runspec_schema["properties"]["kind"]["const"] == "ctxbench.runspec"

    assert plan_schema["$id"] == "https://ctxbench-benchmark.org/schemas/runplan.schema.json"
    assert plan_schema["title"] == "CTXBench RunPlan"
    assert plan_schema["properties"]["kind"]["const"] == "ctxbench.runplan"
