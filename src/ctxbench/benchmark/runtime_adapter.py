"""Translation between benchmark trial records and runtime contracts."""
from __future__ import annotations

from typing import Any

from ctxbench.benchmark.models import EvaluationResult, RunTiming, TrialResult, TrialSpec, TrialTrace
from ctxbench.core.provisioning import ProvisioningConfiguration
from ctxbench.runtime.models import ExecutionResult, RuntimeRequest
from ctxbench.util.logging import trial_log_context


class TrialRuntimeAdapter:
    """Translate benchmark records without performing runtime work."""

    def to_runtime_request(self, trial: TrialSpec) -> RuntimeRequest:
        return RuntimeRequest(
            task=trial.taskStatement,
            task_id=trial.taskId,
            instance_id=trial.instanceId,
            provider=trial.provider,
            model_name=str(trial.params.get("model_name", "")),
            configuration=ProvisioningConfiguration(
                strategy=trial.strategy,
                representation=trial.representation,
                surface=trial.surface,
            ),
            surface_spec=dict(trial.surfaceSpec),
            params=dict(trial.params),
            metadata=_request_metadata(trial),
            cache_model_name=str(trial.modelName or trial.params.get("model_name") or ""),
        )

    def to_trial_result(self, trial: TrialSpec, execution: ExecutionResult) -> TrialResult:
        ai_result = execution.ai_result
        is_empty_answer = ai_result.error is None and not (ai_result.answer or "").strip()
        error_message = ai_result.error or ("Model returned empty answer" if is_empty_answer else None)
        status = "error" if error_message is not None else "success"

        trace = TrialTrace()
        if trial.trace.enabled:
            trace.aiTrace = ai_result.trace
            if trial.trace.save_tool_calls:
                trace.toolCalls = ai_result.tool_calls
            native_mcp = ai_result.metadata.get("native_mcp")
            if isinstance(native_mcp, dict):
                trace.nativeMcp = native_mcp
            server_mcp = ai_result.metadata.get("server_mcp")
            if isinstance(server_mcp, list):
                trace.serverMcp = [item for item in server_mcp if isinstance(item, dict)]
            if trial.trace.save_raw_response:
                trace.rawResponse = ai_result.raw_response
            if trial.trace.save_errors:
                trace.error = error_message

        usage = ai_result.usage if trial.trace.save_usage or status == "error" else {}
        return TrialResult(
            trialId=trial.trialId,
            experimentId=trial.experimentId,
            dataset=trial.dataset,
            taskId=trial.taskId,
            taskStatement=trial.taskStatement,
            taskTemplate=trial.taskTemplate,
            taskTags=list(trial.taskTags),
            validationType=trial.validationType,
            validationConfig=dict(trial.validationConfig),
            contextBlocks=list(trial.contextBlocks),
            parameters=dict(trial.parameters),
            instanceId=trial.instanceId,
            provider=trial.provider,
            modelId=trial.modelId,
            modelName=trial.modelName,
            strategy=trial.strategy,
            representation=trial.representation,
            surface=trial.surface,
            configurationId=trial.configurationId,
            repeatIndex=trial.repeatIndex,
            outputRoot=trial.outputRoot,
            response=ai_result.answer,
            status=status,
            errorMessage=error_message,
            timing=RunTiming(
                startedAt=execution.started_at,
                finishedAt=execution.finished_at,
                durationMs=execution.duration_ms,
            ),
            usage=usage,
            metricsSummary=build_metrics_summary(ai_trace=trace.aiTrace, strategy=trial.strategy),
            trace=trace,
            evaluation=EvaluationResult(),
            metadata=trial.metadata,
            surfaceSpec=dict(trial.surfaceSpec),
        )


def _request_metadata(trial: TrialSpec) -> dict[str, Any]:
    return {
        **trial_log_context(trial),
        "trialId": trial.trialId,
        "experimentId": trial.experimentId,
        "taskId": trial.taskId,
        "instanceId": trial.instanceId,
        "phase": "EXECUTE",
        "representation": trial.representation,
        "surface": trial.surface,
        "provider": trial.provider,
        "modelId": trial.modelId,
        "modelName": trial.modelName,
        "configurationId": trial.configurationId,
        "strategy": trial.strategy,
        "repeatIndex": trial.repeatIndex,
        "validationType": trial.validationType,
        "instance_id": trial.instanceId,
        "task_tags": list(trial.taskTags),
        "validation_type": trial.validationType,
        "context_representation": trial.representation,
        "context_obtained": trial.strategy == "inline",
        "surface_spec": dict(trial.surfaceSpec),
    }


def build_metrics_summary(*, ai_trace: dict[str, object], strategy: str) -> dict[str, int | None]:
    metrics = ai_trace.get("metrics", {}) if isinstance(ai_trace, dict) else {}
    if not isinstance(metrics, dict):
        metrics = {}
    legacy_task_statement_chars_key = "question" + "Chars"
    summary: dict[str, int | None] = {
        "totalDurationMs": _as_int(metrics.get("totalDurationMs")),
        "strategyDurationMs": _as_int(metrics.get("strategyDurationMs")),
        "modelDurationMs": _as_int(metrics.get("modelDurationMs")),
        "toolDurationMs": _as_int(metrics.get("toolDurationMs")),
        "benchmarkDurationMsEstimated": _as_int(metrics.get("benchmarkDurationMsEstimated")),
        "loopControlDurationMsEstimated": _as_int(metrics.get("loopControlDurationMsEstimated")),
        "modelCalls": _as_int(metrics.get("modelCalls")),
        "mcpToolCalls": _as_int(metrics.get("mcpToolCalls")),
        "toolCalls": _as_int(metrics.get("toolCalls")),
        "functionCalls": _as_int(metrics.get("functionCalls")),
        "steps": _as_int(metrics.get("steps")),
        "retryCount": _as_int(metrics.get("retryCount")),
        "inputTokens": _as_int(metrics.get("inputTokens")),
        "outputTokens": _as_int(metrics.get("outputTokens")),
        "totalTokens": _as_int(metrics.get("totalTokens")),
        "totalTokensEstimated": _as_int(metrics.get("totalTokensEstimated")),
        "cachedInputTokens": _as_int(metrics.get("cachedInputTokens")),
        "cacheReadInputTokens": _as_int(metrics.get("cacheReadInputTokens")),
        "cacheCreationInputTokens": _as_int(metrics.get("cacheCreationInputTokens")),
        "taskStatementTokensEstimated": _as_int(metrics.get("taskStatementTokensEstimated", metrics.get("questionTokensEstimated"))),
        "estimatedInputTokens": _as_int(metrics.get("estimatedInputTokens")),
        "estimatedOutputTokens": _as_int(metrics.get("estimatedOutputTokens")),
        "reservedTokens": _as_int(metrics.get("reservedTokens")),
        "contextChars": _as_int(metrics.get("contextChars")),
        "contextBytes": _as_int(metrics.get("contextBytes")),
        "taskStatementChars": _as_int(
            metrics.get("taskStatementChars", metrics.get(legacy_task_statement_chars_key))
        ),
        "promptChars": _as_int(metrics.get("promptChars")),
        "rateLimitWaitMs": _as_int(metrics.get("rateLimitWaitMs")),
        "retrySleepMs": _as_int(metrics.get("retrySleepMs")),
    }
    if strategy == "inline":
        summary["toolDurationMs"] = 0
        summary["toolCalls"] = 0
        summary["functionCalls"] = 0
        summary["mcpToolCalls"] = 0
    return summary


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
