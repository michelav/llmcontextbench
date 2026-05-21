from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from ctxbench.ai.cache import build_judge_prompt_cache_key
from ctxbench.ai.engine import Engine
from ctxbench.ai.models.base import AIRequest, ModelInput
from ctxbench.adapters.registry import get_default_registry
from ctxbench.benchmark.models import (
    DatasetProvenance,
    EvaluationBatchSummary,
    EvaluationItemResult,
    EvaluationJudgeInfo,
    EvaluationModelConfig,
    EvaluationRunResult,
    EvaluationRunSummary,
    EvaluationTrace,
    RunResult,
)
from ctxbench.dataset.errors import AdapterUnavailableError
from ctxbench.dataset.package import DatasetPackage
from ctxbench.dataset.payloads import OracleUnavailable
from ctxbench.dataset.provider import LocalDatasetPackage

EVALUATION_SYSTEM_INSTRUCTION = (
    "You are evaluating benchmark answers.\n"
    "Use only the provided question, answer and curriculum context.\n"
    "Do not use external knowledge.\n"
    "Return only the requested JSON."
)

JUDGE_PROMPT_PREFIX = """You are an evaluation assistant for a benchmark. Your task is to evaluate an answer given by a model based strictly on the provided curriculum context and criteria.
You must be objective, consistent, and conservative in your evaluation.
Do NOT use external knowledge. Only use the provided curriculum context.
Your output must strictly follow the requested JSON format.
Evaluate the answer to the question based on the provided curriculum context.

# Evaluation Instructions
- Use only the provided curriculum context.
- If the curriculum context is silent about something, treat that as missing support.
- Be strict: if unsure, prefer "partial" or "misses".
- Each criterion MUST include a short justification grounded in the provided curriculum context.
- Do NOT include chain-of-thought or hidden reasoning. Provide only concise criterion justifications.

# Evaluation Scale

Use the following scale for ALL criteria:

- "meets": fully satisfies the criterion
- "partial": partially satisfies the criterion, with minor issues or omissions
- "misses": does not satisfy the criterion or has major issues

# Evaluation Criteria

## Correctness
The answer must be factually correct according to the curriculum context.
- Check whether the information provided is accurate.
- Use the curriculum context as the source of truth.
- Check whether the answer does not contradict the curriculum context.
- Penalize claims that are not supported by the curriculum context, unless they are clearly marked as uncertainty or inference grounded in the context.

## Completeness
The answer must fully address the question according to what can be answered from the curriculum context.
- Check whether all parts of the question are answered.
- Penalize important omissions relative to the curriculum context.
- Do not penalize missing information when the curriculum context itself does not provide enough evidence to answer that part of the question.
- Prefer answers that explicitly acknowledge when the curriculum context lacks enough information.

# Output Format (STRICT JSON)
Return ONLY a JSON object in the following format:

{{
  "correctness": {{
    "rating": "meets | partial | misses",
    "justification": "short justification"
  }},
  "completeness": {{
    "rating": "meets | partial | misses",
    "justification": "short justification"
  }}
}}

# Curriculum Context
{curriculum_context}
"""

JUDGE_PROMPT_SUFFIX = """
# Question
{question}

# Candidate Answer
{answer}

"""

JUDGE_PROMPT = JUDGE_PROMPT_PREFIX + JUDGE_PROMPT_SUFFIX

_RATING_ALIASES: dict[str, str] = {
    "meets": "meets",
    "partial": "partial",
    "partially meets": "partial",
    "misses": "misses",
    "does not meet": "misses",
}

_RATING_ORDER: dict[str, int] = {"meets": 2, "partial": 1, "misses": 0}

JUDGE_STRUCTURED_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "correctness": {
            "type": "object",
            "properties": {
                "rating": {
                    "type": "string",
                    "enum": ["meets", "partial", "misses"],
                },
                "justification": {"type": "string"},
            },
            "required": ["rating", "justification"],
            "additionalProperties": False,
        },
        "completeness": {
            "type": "object",
            "properties": {
                "rating": {
                    "type": "string",
                    "enum": ["meets", "partial", "misses"],
                },
                "justification": {"type": "string"},
            },
            "required": ["rating", "justification"],
            "additionalProperties": False,
        },
    },
    "required": ["correctness", "completeness"],
    "additionalProperties": False,
}


def _resolve_adapter(dataset: DatasetProvenance) -> DatasetPackage:
    try:
        return get_default_registry().resolve(dataset)
    except AdapterUnavailableError as exc:
        local_root = dataset.materialized_path or getattr(dataset, "root", None)
        if local_root:
            return LocalDatasetPackage.from_dataset(dataset)
        raise AdapterUnavailableError(str(exc)) from exc


def _normalize_rating(raw: str | None) -> str:
    if not isinstance(raw, str):
        return "misses"
    return _RATING_ALIASES.get(raw.strip().lower(), raw.strip().lower())


@dataclass(frozen=True)
class EvaluationJob:
    custom_id: str
    result: RunResult
    judge: EvaluationModelConfig
    prompt: str
    question_text: str
    context_payload: dict[str, Any]
    curriculum_context: str
    evidence_obtained: bool
    oracle_available: bool
    oracle_used: bool = False


def judge_identifier(config: EvaluationModelConfig) -> str:
    for key in ("id", "judgeId", "judge_id", "name"):
        value = config.params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{config.provider}:{config.model}"


def batch_custom_id(result: RunResult, judge: EvaluationModelConfig) -> str:
    judge_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", judge_identifier(judge)).strip("-_")
    if not judge_slug:
        judge_slug = "judge"
    return f"{result.runId}-{judge_slug}"[:64]


def build_evaluation_job(
    result: RunResult,
    adapter: DatasetPackage,
    *,
    judge: EvaluationModelConfig,
    only: str | None = None,
    mode: str | None = None,
    event_logger: Callable[[str, str, dict[str, object]], None] | None = None,
) -> EvaluationJob | None:
    if result.status != "success":
        return None
    if only and result.questionId != only:
        return None

    rendered_question = result.question
    validation_type = result.validationType or result.metadata.validationType
    if mode and validation_type != mode:
        return None
    if validation_type != "judge":
        raise ValueError(f"Unsupported validation type: {validation_type}")

    evidence_payload = adapter.get_evidence(result.instanceId, result.questionId)
    oracle_result = adapter.get_oracle(result.instanceId, result.questionId)
    oracle_available = not isinstance(oracle_result, OracleUnavailable)
    block_ids = _evidence_task_context_blocks(evidence_payload.task)
    context_payload, missing = _get_context_blocks(evidence_payload.evidence, block_ids)
    if missing:
        if event_logger is not None:
            event_logger(
                "SKIP",
                "Context blocks not found, skipping evaluation job",
                {
                    "runId": result.runId,
                    "questionId": result.questionId,
                    "instanceId": result.instanceId,
                    "missingBlocks": missing,
                },
            )
        return None
    curriculum_context = _format_curriculum_context(context_payload)
    prompt = JUDGE_PROMPT.format(
        question=rendered_question,
        answer=result.answer,
        curriculum_context=curriculum_context,
    )
    return EvaluationJob(
        custom_id=batch_custom_id(result, judge),
        result=result,
        judge=judge,
        prompt=prompt,
        question_text=rendered_question,
        context_payload=context_payload,
        curriculum_context=curriculum_context,
        evidence_obtained=True,
        oracle_available=oracle_available,
        oracle_used=False,
    )


def build_evaluation_jobs(
    results: Iterable[RunResult],
    *,
    judges: list[EvaluationModelConfig],
    only: str | None = None,
    mode: str | None = None,
    event_logger: Callable[[str, str, dict[str, object]], None] | None = None,
) -> list[EvaluationJob]:
    adapter_cache: dict[tuple[str | None, str | None, str | None], DatasetPackage] = {}
    jobs: list[EvaluationJob] = []
    ordered_results = sorted(
        list(results),
        key=lambda item: (
            tuple(sorted(item.contextBlock or [])),
            str(item.instanceId),
            str(item.questionId),
            str(item.provider),
            str(item.modelName or ""),
            str(item.runId),
        ),
    )
    for result in ordered_results:
        adapter_key = (
            result.dataset.id,
            result.dataset.version,
            result.dataset.materialized_path or result.dataset.origin,
        )
        adapter = adapter_cache.get(adapter_key)
        if adapter is None:
            adapter = _resolve_adapter(result.dataset)
            adapter_cache[adapter_key] = adapter
        for judge in judges:
            job = build_evaluation_job(
                result,
                adapter,
                judge=judge,
                only=only,
                mode=mode,
                event_logger=event_logger,
            )
            if job is not None:
                jobs.append(job)
    return jobs


def _judge_request(
    *,
    config: EvaluationModelConfig,
    prompt: str,
    answer_text: str,
    run_id: str,
    exp_id: str,
    instance_id: str,
    question_id: str,
    question_text: str,
    curriculum_context: str,
    engine: Engine,
) -> tuple[dict[str, Any] | None, EvaluationJudgeInfo, EvaluationTrace]:
    request_params = {
        "temperature": config.temperature,
        **config.params,
    }
    request_params.setdefault(
        "structured_output",
        {
            "name": "judge_response",
            "strict": True,
            "schema": JUDGE_STRUCTURED_OUTPUT_SCHEMA,
        },
    )
    provider_lower = config.provider.lower()
    if provider_lower.startswith("openai"):
        request_params.setdefault(
            "prompt_cache_key",
            build_judge_prompt_cache_key(
                model_name=config.model,
                instance_id=instance_id,
                context=curriculum_context,
            ),
        )
    is_claude = provider_lower.startswith("anthropic") or provider_lower.startswith("claude")
    if is_claude:
        request_params["prompt_cache_prefix"] = JUDGE_PROMPT_PREFIX.format(
            curriculum_context=curriculum_context
        )
        effective_prompt = JUDGE_PROMPT_SUFFIX.format(
            question=question_text,
            answer=answer_text,
        )
    else:
        effective_prompt = prompt
    request = AIRequest(
        question=effective_prompt,
        context="{}",
        provider_name=config.provider,
        model_name=config.model,
        strategy_name="inline",
        context_format="text",
        system_instruction=EVALUATION_SYSTEM_INSTRUCTION,
        params=request_params,
        metadata={
            "run_id": run_id,
            "expId": exp_id,
            "phase": "evaluation",
            "judge_role": "judge",
        },
    )
    model_input = ModelInput(
        system_instruction=EVALUATION_SYSTEM_INSTRUCTION,
        prompt=effective_prompt,
    )
    result = engine.execute_model_input(request, model_input)
    trace = EvaluationTrace(
        aiTrace=result.trace,
        rawResponse=result.raw_response,
        error=result.error,
    )
    metrics = result.trace.get("metrics", {}) if isinstance(result.trace, dict) else {}
    info = EvaluationJudgeInfo(
        used=True,
        role="judge",
        provider=config.provider,
        model=config.model,
        inputTokens=result.usage.get("inputTokens"),
        outputTokens=result.usage.get("outputTokens"),
        durationMs=metrics.get("totalDurationMs"),
    )
    if result.error:
        return None, info, trace
    try:
        return json.loads(result.answer.strip()), info, trace
    except json.JSONDecodeError:
        return None, info, trace


def _evaluate_judge(
    result: RunResult,
    question_text: str,
    context_payload: dict[str, Any],
    judges: list[EvaluationModelConfig],
    engine: Engine,
) -> tuple[dict[str, Any], EvaluationJudgeInfo, EvaluationTrace]:
    if not judges:
        return {
            "evaluationMethod": "judge",
            "error": "Experiment evaluation.judges is required for judge validation.",
        }, EvaluationJudgeInfo(), EvaluationTrace()
    curriculum_context = _format_curriculum_context(context_payload)
    prompt = JUDGE_PROMPT.format(
        question=question_text,
        answer=result.answer,
        curriculum_context=curriculum_context,
    )
    judge_votes: list[dict[str, Any]] = []
    judge_infos: list[EvaluationJudgeInfo] = []
    traces: list[EvaluationTrace] = []
    valid_votes: list[dict[str, Any]] = []
    for config in judges:
        payload, judge_info, trace = _judge_request(
            config=config,
            prompt=prompt,
            answer_text=result.answer,
            run_id=result.runId,
            exp_id=result.experimentId,
            instance_id=result.instanceId,
            question_id=result.questionId,
            question_text=question_text,
            curriculum_context=curriculum_context,
            engine=engine,
        )
        judge_infos.append(judge_info)
        traces.append(trace)
        if payload is None:
            judge_votes.append({
                "judgeId": judge_identifier(config),
                "provider": config.provider,
                "model": config.model,
                "status": "error",
                "inputTokens": judge_info.inputTokens,
                "outputTokens": judge_info.outputTokens,
                "durationMs": judge_info.durationMs,
                "error": "Judge did not return valid JSON.",
            })
            continue
        correctness = _criterion_payload(payload.get("correctness"))
        completeness = _criterion_payload(payload.get("completeness"))
        vote = {
            "judgeId": judge_identifier(config),
            "provider": config.provider,
            "model": config.model,
            "status": "evaluated",
            "correctness": correctness,
            "completeness": completeness,
            "inputTokens": judge_info.inputTokens,
            "outputTokens": judge_info.outputTokens,
            "durationMs": judge_info.durationMs,
        }
        judge_votes.append(vote)
        valid_votes.append(vote)

    merged_info = _merge_judge_infos(judge_infos)
    merged_trace = _merge_evaluation_traces(traces)
    if not valid_votes:
        return {
            "evaluationMethod": "judge",
            "contextBlocks": list(context_payload.keys()),
            "judges": judge_votes,
            "error": "Judge did not return valid JSON.",
        }, merged_info, merged_trace
    agg_correctness = _aggregate_votes(valid_votes, "correctness")
    agg_completeness = _aggregate_votes(valid_votes, "completeness")
    return {
        "evaluationMethod": "judge",
        "contextBlocks": list(context_payload.keys()),
        "judges": judge_votes,
        "outcome": {
            "correctness": agg_correctness,
            "completeness": agg_completeness,
        },
    }, merged_info, merged_trace


def evaluation_from_judge_payload(
    job: EvaluationJob,
    *,
    payload: dict[str, Any] | None,
    judge_info: EvaluationJudgeInfo,
    trace: EvaluationTrace,
) -> EvaluationRunResult:
    judge_id = judge_identifier(job.judge)
    if payload is None:
        details = {
            "evaluationMethod": "judge",
            "contextBlocks": list(job.context_payload.keys()),
            "evidence_obtained": job.evidence_obtained,
            "oracle_available": job.oracle_available,
            "oracle_used": job.oracle_used,
            "judges": [{
                "judgeId": judge_id,
                "provider": job.judge.provider,
                "model": job.judge.model,
                "status": "error",
                "inputTokens": judge_info.inputTokens,
                "outputTokens": judge_info.outputTokens,
                "durationMs": judge_info.durationMs,
                "error": "Judge did not return valid JSON.",
            }],
            "error": "Judge did not return valid JSON.",
        }
    else:
        correctness = _criterion_payload(payload.get("correctness"))
        completeness = _criterion_payload(payload.get("completeness"))
        vote = {
            "judgeId": judge_id,
            "provider": job.judge.provider,
            "model": job.judge.model,
            "status": "evaluated",
            "correctness": correctness,
            "completeness": completeness,
            "inputTokens": judge_info.inputTokens,
            "outputTokens": judge_info.outputTokens,
            "durationMs": judge_info.durationMs,
        }
        agg_correctness = _aggregate_votes([vote], "correctness")
        agg_completeness = _aggregate_votes([vote], "completeness")
        details = {
            "evaluationMethod": "judge",
            "contextBlocks": list(job.context_payload.keys()),
            "evidence_obtained": job.evidence_obtained,
            "oracle_available": job.oracle_available,
            "oracle_used": job.oracle_used,
            "judges": [vote],
            "outcome": {
                "correctness": agg_correctness,
                "completeness": agg_completeness,
            },
        }
    return _build_evaluation_result(
        job.result,
        question_text=job.question_text,
        validation_type="judge",
        details=details,
        judge_info=judge_info,
        trace=_with_evaluation_trace_metadata(
            trace,
            evidence_obtained=job.evidence_obtained,
            oracle_available=job.oracle_available,
            oracle_used=job.oracle_used,
        ),
    )


def _build_skipped_evaluation_result(
    result: RunResult,
    question_text: str,
    *,
    missing_blocks: list[str],
) -> EvaluationRunResult:
    error_msg = f"Context blocks not found: {', '.join(missing_blocks)}"
    details: dict[str, Any] = {
        "evaluationMethod": "judge",
        "contextBlocks": [],
        "error": error_msg,
    }
    item = EvaluationItemResult(
        experimentId=result.experimentId,
        runId=result.runId,
        dataset=result.dataset,
        questionId=result.questionId,
        instanceId=result.instanceId,
        question=question_text,
        evaluationMode="judge",
        status="skipped",
        evaluationMethod="judge",
        details=details,
        executionModel=result.modelName,
        executionStrategy=result.strategy,
        executionFormat=result.format,
        executionInputTokens=result.usage.get("inputTokens"),
        executionOutputTokens=result.usage.get("outputTokens"),
        executionDurationMs=result.timing.durationMs,
        questionTags=list(result.questionTags),
    )
    return EvaluationRunResult(
        experimentId=result.experimentId,
        runId=result.runId,
        dataset=result.dataset,
        questionId=result.questionId,
        items=[item],
        summary=EvaluationRunSummary(itemCount=1),
        metadata=result.metadata,
    )


def _build_evaluation_result(
    result: RunResult,
    *,
    question_text: str,
    validation_type: str,
    details: dict[str, Any],
    judge_info: EvaluationJudgeInfo,
    trace: EvaluationTrace,
) -> EvaluationRunResult:
    metrics = result.trace.aiTrace.get("metrics", {}) if result.trace.aiTrace else {}
    summary = result.metricsSummary
    context_blocks = details.get("contextBlocks") if isinstance(details, dict) else None
    item = EvaluationItemResult(
        experimentId=result.experimentId,
        runId=result.runId,
        dataset=result.dataset,
        questionId=result.questionId,
        instanceId=result.instanceId,
        question=question_text,
        evaluationMode=validation_type,
        status="evaluated",
        evaluationMethod=details.get("evaluationMethod"),
        details=details,
        contextBlock=context_blocks if isinstance(context_blocks, list) and context_blocks else None,
        executionModel=result.modelName,
        executionStrategy=result.strategy,
        executionFormat=result.format,
        executionInputTokens=result.usage.get("inputTokens"),
        executionOutputTokens=result.usage.get("outputTokens"),
        executionDurationMs=result.timing.durationMs,
        executionToolCalls=summary.get("toolCalls", metrics.get("toolCalls")),
        executionFunctionCalls=summary.get("functionCalls", metrics.get("functionCalls")),
        executionLlmCalls=summary.get("modelCalls", metrics.get("modelCalls")),
        questionTags=list(result.questionTags),
        evaluationJudgeUsed=judge_info.used,
        evaluationJudgeRole=judge_info.role,
        evaluationJudgeProvider=judge_info.provider,
        evaluationJudgeModel=judge_info.model,
        evaluationInputTokens=judge_info.inputTokens,
        evaluationOutputTokens=judge_info.outputTokens,
        evaluationDurationMs=judge_info.durationMs,
        evaluationTrace=trace,
    )
    return EvaluationRunResult(
        experimentId=result.experimentId,
        runId=result.runId,
        dataset=result.dataset,
        questionId=result.questionId,
        items=[item],
        summary=EvaluationRunSummary(itemCount=1),
        metadata=result.metadata,
    )


def _get_context_blocks(
    blocks: object,
    block_ids: list[str],
) -> tuple[dict[str, Any], list[str]]:
    """Returns (found_blocks_dict, missing_block_ids).

    Supports both wrapped format {"blocks": {id: block, ...}} and flat {id: block, ...}.
    """
    if not isinstance(blocks, dict):
        return {}, list(block_ids)
    nested = blocks.get("blocks")
    inner: dict[str, Any] = nested if isinstance(nested, dict) else blocks
    found: dict[str, Any] = {}
    missing: list[str] = []
    for bid in block_ids:
        block = inner.get(bid)
        if block is None:
            missing.append(bid)
        else:
            found[bid] = block
    return found, missing


def _evidence_task_context_blocks(task: object) -> list[str]:
    if not isinstance(task, dict):
        return []
    raw_blocks = task.get("context_blocks", [])
    if not isinstance(raw_blocks, list):
        return []
    return [str(block_id) for block_id in raw_blocks]


def _with_evaluation_trace_metadata(
    trace: EvaluationTrace,
    *,
    evidence_obtained: bool,
    oracle_available: bool,
    oracle_used: bool,
) -> EvaluationTrace:
    ai_trace = dict(trace.aiTrace or {})
    metadata = dict(ai_trace.get("metadata") or {})
    metadata.update(
        {
            "evidence_obtained": evidence_obtained,
            "oracle_available": oracle_available,
            "oracle_used": oracle_used,
        }
    )
    ai_trace["metadata"] = metadata
    return EvaluationTrace(
        aiTrace=ai_trace,
        rawResponse=trace.rawResponse,
        error=trace.error,
    )


def _format_curriculum_context(context_payload: dict[str, Any]) -> str:
    if not context_payload:
        return ""
    parts: list[str] = []
    for block_id, block in context_payload.items():
        if isinstance(block, dict):
            title = block.get("title", block_id)
            content = block.get("content", "")
            parts.append(f"## {title}\n{content}")
        else:
            parts.append(str(block))
    return "\n\n".join(parts)


def _criterion_payload(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        rating = _normalize_rating(value.get("rating"))
        justification = str(value.get("justification", "")).strip()
        return {"rating": rating, "justification": justification}
    return {"rating": _normalize_rating(str(value or "").strip()), "justification": ""}


def recompute_judge_outcome(judge_votes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Recompute the outcome dict from a list of judge vote dicts (details.judges format)."""
    valid = [v for v in judge_votes if not v.get("error")]
    if not valid:
        return None
    return {
        "correctness": _aggregate_votes(valid, "correctness"),
        "completeness": _aggregate_votes(valid, "completeness"),
    }


def _aggregate_votes(votes: list[dict[str, Any]], criterion: str) -> dict[str, Any]:
    ratings: list[str] = []
    for vote in votes:
        payload = vote.get(criterion)
        if isinstance(payload, dict):
            ratings.append(_normalize_rating(payload.get("rating")))
        elif isinstance(payload, str):
            ratings.append(_normalize_rating(payload))
    if not ratings:
        return {"rating": "misses", "agreement": True}
    counter: dict[str, int] = {}
    for r in ratings:
        counter[r] = counter.get(r, 0) + 1
    best = max(counter, key=lambda k: (counter[k], _RATING_ORDER.get(k, 0)))
    return {"rating": best, "agreement": counter[best] > len(ratings) / 2}


def _merge_judge_infos(judge_infos: list[EvaluationJudgeInfo]) -> EvaluationJudgeInfo:
    used_infos = [item for item in judge_infos if item.used]
    if not used_infos:
        return EvaluationJudgeInfo()
    providers = {item.provider for item in used_infos if item.provider}
    models = {item.model for item in used_infos if item.model}
    input_tokens = [item.inputTokens for item in used_infos if item.inputTokens is not None]
    output_tokens = [item.outputTokens for item in used_infos if item.outputTokens is not None]
    durations = [item.durationMs for item in used_infos if item.durationMs is not None]
    return EvaluationJudgeInfo(
        used=True,
        role="judges",
        provider=next(iter(providers)) if len(providers) == 1 else None,
        model=next(iter(models)) if len(models) == 1 else None,
        inputTokens=sum(input_tokens) if input_tokens else None,
        outputTokens=sum(output_tokens) if output_tokens else None,
        durationMs=sum(durations) if durations else None,
    )


def _merge_evaluation_traces(traces: list[EvaluationTrace]) -> EvaluationTrace:
    return EvaluationTrace(
        aiTrace={
            "judges": [trace.aiTrace for trace in traces if trace.aiTrace]
        },
        rawResponse=[trace.rawResponse for trace in traces if trace.rawResponse is not None],
        error="; ".join(trace.error for trace in traces if trace.error) or None,
    )


def evaluate_run_result(
    result: RunResult,
    adapter: DatasetPackage,
    *,
    judges: list[EvaluationModelConfig],
    only: str | None = None,
    mode: str | None = None,
    engine: Engine | None = None,
    event_logger: Callable[[str, str, dict[str, object]], None] | None = None,
) -> EvaluationRunResult | None:
    if result.status != "success":
        return None
    if only and result.questionId != only:
        return None

    rendered_question = result.question
    validation_type = result.validationType or result.metadata.validationType
    if mode and validation_type != mode:
        return None
    active_engine = engine or Engine()
    if event_logger is not None:
        event_logger(
            "EVALUATE",
            "Starting evaluation",
            {
                "runId": result.runId,
                "questionId": result.questionId,
                "validationType": validation_type,
            },
        )
    if validation_type == "judge":
        evidence_payload = adapter.get_evidence(result.instanceId, result.questionId)
        oracle_result = adapter.get_oracle(result.instanceId, result.questionId)
        oracle_available = not isinstance(oracle_result, OracleUnavailable)
        block_ids = _evidence_task_context_blocks(evidence_payload.task)
        context_payload, missing = _get_context_blocks(evidence_payload.evidence, block_ids)
        if missing:
            if event_logger is not None:
                event_logger(
                    "SKIP",
                    "Context blocks not found, evaluation skipped",
                    {
                        "runId": result.runId,
                        "questionId": result.questionId,
                        "instanceId": result.instanceId,
                        "missingBlocks": missing,
                    },
                )
            return _build_skipped_evaluation_result(result, rendered_question, missing_blocks=missing)
        details, judge_info, trace = _evaluate_judge(
            result,
            rendered_question,
            context_payload,
            judges,
            active_engine,
        )
        details["evidence_obtained"] = True
        details["oracle_available"] = oracle_available
        details["oracle_used"] = False
        trace = _with_evaluation_trace_metadata(
            trace,
            evidence_obtained=True,
            oracle_available=oracle_available,
            oracle_used=False,
        )
    else:
        raise ValueError(f"Unsupported validation type: {validation_type}")

    if event_logger is not None:
        event_logger(
            "EVALUATE",
            "Evaluation completed",
            {
                "runId": result.runId,
                "questionId": result.questionId,
                "validationType": validation_type,
                "outcome": details.get("outcome"),
            },
        )
    return _build_evaluation_result(
        result,
        question_text=rendered_question,
        validation_type=validation_type,
        details=details,
        judge_info=judge_info,
        trace=trace,
    )


def evaluate_run_results(
    results: Iterable[RunResult],
    *,
    judges: list[EvaluationModelConfig],
    only: str | None = None,
    mode: str | None = None,
    continue_on_error: bool = False,
    event_logger: Callable[[str, str, dict[str, object]], None] | None = None,
    on_result: Callable[[RunResult, EvaluationRunResult | None], None] | None = None,
) -> list[EvaluationRunResult]:
    adapter_cache: dict[tuple[str | None, str | None, str | None], DatasetPackage] = {}
    engine = Engine(event_logger=event_logger)
    evaluations: list[EvaluationRunResult] = []
    ordered_results = sorted(
        list(results),
        key=lambda item: (
            tuple(sorted(item.contextBlock or [])),
            str(item.instanceId),
            str(item.questionId),
            str(item.provider),
            str(item.modelName or ""),
            str(item.runId),
        ),
    )
    try:
        for result in ordered_results:
            try:
                adapter_key = (
                    result.dataset.id,
                    result.dataset.version,
                    result.dataset.materialized_path or result.dataset.origin,
                )
                adapter = adapter_cache.get(adapter_key)
                if adapter is None:
                    adapter = _resolve_adapter(result.dataset)
                    adapter_cache[adapter_key] = adapter
                evaluated = evaluate_run_result(
                    result,
                    adapter,
                    judges=judges,
                    only=only,
                    mode=mode,
                    engine=engine,
                    event_logger=event_logger,
                )
                if evaluated is not None:
                    evaluations.append(evaluated)
                if on_result is not None:
                    on_result(result, evaluated)
            except Exception:
                if not continue_on_error:
                    raise
    finally:
        engine.close()
    return evaluations


def build_evaluation_summary_rows(rows: Iterable[dict[str, Any]]) -> EvaluationBatchSummary:
    row_list = list(rows)
    experiment_id = str(row_list[0].get("experimentId", "")) if row_list else ""
    return EvaluationBatchSummary(
        experimentId=experiment_id,
        runCount=len(row_list),
        itemCount=len(row_list),
        questions=[_build_evaluation_question_summary(row) for row in row_list],
    )


def _build_evaluation_question_summary(row: dict[str, Any]) -> dict[str, Any]:
    outcome = row.get("outcome")
    if not isinstance(outcome, dict):
        outcome = {}
    correctness_obj = outcome.get("correctness") or {}
    completeness_obj = outcome.get("completeness") or {}
    return {
        "trialId": row.get("trialId"),
        "taskId": row.get("taskId"),
        "instanceId": row.get("instanceId"),
        "status": row.get("status"),
        "evaluationMethod": row.get("evaluationMethod"),
        "judgeCount": row.get("judgeCount"),
        "judgeErrorCount": row.get("judgeErrorCount"),
        "outcome": {
            "correctness": {
                "rating": correctness_obj.get("rating"),
                "agreement": correctness_obj.get("agreement"),
            },
            "completeness": {
                "rating": completeness_obj.get("rating"),
                "agreement": completeness_obj.get("agreement"),
            },
        },
    }
