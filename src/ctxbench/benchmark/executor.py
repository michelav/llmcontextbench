from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ctxbench.adapters.registry import get_default_registry
from ctxbench.ai.cache import build_inline_prompt_cache_key
from ctxbench.ai.engine import Engine
from ctxbench.ai.models.base import AIRequest
from ctxbench.ai.runtime import LocalFunctionRuntime, MCPRuntime
from ctxbench.benchmark.models import EvaluationResult, TrialResult, RunTiming, TrialTrace, TrialSpec
from ctxbench.dataset.errors import AdapterUnavailableError, CapabilityUnavailableError
from ctxbench.dataset.package import DatasetPackage
from ctxbench.dataset.provider import LocalDatasetPackage
from ctxbench.util.clock import utc_now_iso

def execute_runspec(runspec: TrialSpec, engine: Engine) -> TrialResult:
    adapter = _resolve_adapter(runspec)
    context = ""
    dataset_tool_provider: object | None = None
    if runspec.strategy == "inline":
        context_payload = adapter.get_context(runspec.instanceId, runspec.taskId, runspec.format)
        context = _context_to_text(context_payload.content)
    elif runspec.strategy in {"local_function", "local_mcp", "remote_mcp"}:
        dataset_tool_provider = adapter.tool_provider()
        if dataset_tool_provider is None:
            raise CapabilityUnavailableError(
                f"Strategy '{runspec.strategy}' requires a dataset tool provider."
            )
    request_params = dict(runspec.params)
    if runspec.strategy == "inline" and runspec.provider.lower().startswith("openai"):
        request_params.setdefault(
            "prompt_cache_key",
            build_inline_prompt_cache_key(
                model_name=str(runspec.modelName or runspec.params.get("model_name") or ""),
                instance_id=runspec.instanceId,
                format_name=runspec.format,
                context=context,
            ),
        )

    request_metadata = {
        "trialId": runspec.trialId,
        "experimentId": runspec.experimentId,
        "taskId": runspec.taskId,
        "instanceId": runspec.instanceId,
        "phase": "execution",
        "format": runspec.format,
        "provider": runspec.provider,
        "instance_id": runspec.instanceId,
        "task_tags": list(runspec.taskTags),
        "validation_type": runspec.validationType,
        "context_representation": runspec.format,
        "context_obtained": runspec.strategy == "inline",
    }
    if runspec.strategy == "remote_mcp":
        request_metadata["dataset_tool_provider"] = dataset_tool_provider

    request_metadata["dataset_instructions"] = adapter.dataset_instructions()
    request = AIRequest(
        question=runspec.taskStatement,
        context=context,
        provider_name=runspec.provider,
        model_name=str(runspec.params.get("model_name", "")),
        strategy_name=runspec.strategy,
        context_format=runspec.format,
        params=request_params,
        metadata=request_metadata,
    )

    started_at = utc_now_iso()
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    active_engine = engine
    owned_engine: Engine | None = None
    if runspec.strategy in {"local_function", "local_mcp"}:
        tool_runtime_factories = _build_tool_runtime_factories(runspec, dataset_tool_provider)
        owned_engine = engine.copy_with_tool_runtime_factories(tool_runtime_factories)
        active_engine = owned_engine
    try:
        ai_result = active_engine.execute(request)
    finally:
        if owned_engine is not None:
            owned_engine.close()
    finished_at = utc_now_iso()
    finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))

    is_empty_answer = ai_result.error is None and not (ai_result.answer or "").strip()
    error_message = ai_result.error or ("Model returned empty answer" if is_empty_answer else None)
    run_status = "error" if error_message is not None else "success"

    trace = TrialTrace()
    if runspec.trace.enabled:
        trace.aiTrace = ai_result.trace
        if runspec.trace.save_tool_calls:
            trace.toolCalls = ai_result.tool_calls
        native_mcp = ai_result.metadata.get("native_mcp")
        if isinstance(native_mcp, dict):
            trace.nativeMcp = native_mcp
        server_mcp = ai_result.metadata.get("server_mcp")
        if isinstance(server_mcp, list):
            trace.serverMcp = [item for item in server_mcp if isinstance(item, dict)]
        if runspec.trace.save_raw_response:
            trace.rawResponse = ai_result.raw_response
        if runspec.trace.save_errors:
            trace.error = error_message

    usage = ai_result.usage if runspec.trace.save_usage or run_status == "error" else {}
    metrics_summary = _build_metrics_summary(
        ai_trace=trace.aiTrace,
        strategy=runspec.strategy,
    )
    result = TrialResult(
        trialId=runspec.trialId,
        experimentId=runspec.experimentId,
        dataset=runspec.dataset,
        taskId=runspec.taskId,
        taskStatement=runspec.taskStatement,
        taskTemplate=runspec.taskTemplate,
        taskTags=list(runspec.taskTags),
        validationType=runspec.validationType,
        contextBlocks=list(runspec.contextBlocks),
        parameters=dict(runspec.parameters),
        instanceId=runspec.instanceId,
        provider=runspec.provider,
        modelId=runspec.modelId,
        modelName=runspec.modelName,
        strategy=runspec.strategy,
        format=runspec.format,
        repeatIndex=runspec.repeatIndex,
        outputRoot=runspec.outputRoot,
        response=ai_result.answer,
        status=run_status,
        errorMessage=error_message,
        timing=RunTiming(
            startedAt=started_at,
            finishedAt=finished_at,
            durationMs=max(0, int((finish - start).total_seconds() * 1000)),
        ),
        usage=usage,
        metricsSummary=metrics_summary,
        trace=trace,
        evaluation=EvaluationResult(),
        metadata=runspec.metadata,
    )
    return result


def _resolve_adapter(runspec: TrialSpec) -> DatasetPackage:
    try:
        return get_default_registry().resolve(runspec.dataset)
    except AdapterUnavailableError as exc:
        materialized_path = runspec.dataset.materialized_path
        if materialized_path and Path(materialized_path).exists():
            return LocalDatasetPackage.from_dataset(runspec.dataset)
        raise AdapterUnavailableError(str(exc)) from exc


def _context_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content)


def _build_tool_runtime_factories(runspec: TrialSpec, service: object) -> dict[str, object]:
    tool_runtime_factories: dict[str, object] = {}
    if runspec.strategy == "local_function":
        tool_runtime_factories["local_function"] = lambda: LocalFunctionRuntime(service)
    if runspec.strategy == "local_mcp":
        server = service if hasattr(service, "app") else None
        if server is not None:
            tool_runtime_factories["local_mcp"] = lambda: MCPRuntime.for_local_server(server)
        else:
            tool_runtime_factories["local_mcp"] = lambda: LocalFunctionRuntime(service)
    return tool_runtime_factories


def _build_metrics_summary(*, ai_trace: dict[str, object], strategy: str) -> dict[str, int | None]:
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
