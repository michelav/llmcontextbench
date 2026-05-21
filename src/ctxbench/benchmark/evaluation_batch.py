from __future__ import annotations

import json
import tempfile
from pathlib import Path
from time import sleep
from typing import Any

from ctxbench.benchmark.evaluation import (
    EVALUATION_SYSTEM_INSTRUCTION,
    JUDGE_STRUCTURED_OUTPUT_SCHEMA,
    EvaluationJob,
    evaluation_from_judge_payload,
    judge_identifier,
)
from ctxbench.benchmark.models import EvaluationJudgeInfo, EvaluationTrialResult, EvaluationTrace
from ctxbench.util.fs import write_json


DEFAULT_BATCH_POLL_INTERVAL_SECONDS = 60
EVALUATION_BATCH_MANIFEST = "evaluation.batch.json"


class AnthropicEvaluationBatchClient:
    provider = "anthropic"

    def __init__(self, *, api_key: str | None = None) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Anthropic SDK is not installed.") from exc
        self._client = Anthropic(api_key=api_key)

    def submit(self, jobs: list[EvaluationJob]) -> Any:
        return self._client.beta.messages.batches.create(
            requests=[_anthropic_batch_request(job) for job in jobs],
        )

    def retrieve(self, batch_id: str) -> Any:
        return self._client.beta.messages.batches.retrieve(batch_id)

    def results(self, batch_id: str, batch: Any | None = None) -> list[Any]:
        return list(self._client.beta.messages.batches.results(batch_id))


class OpenAIEvaluationBatchClient:
    provider = "openai"

    def __init__(self, *, api_key: str | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("OpenAI SDK is not installed.") from exc
        self._client = OpenAI(api_key=api_key)

    def submit(self, jobs: list[EvaluationJob]) -> Any:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8") as file:
            for job in jobs:
                file.write(json.dumps(_openai_batch_request(job), ensure_ascii=False))
                file.write("\n")
            file.flush()
            uploaded = self._client.files.create(file=Path(file.name), purpose="batch")
        return self._client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/responses",
            completion_window="24h",
            metadata={"experimentId": jobs[0].result.experimentId, "judgeId": judge_identifier(jobs[0].judge)},
        )

    def retrieve(self, batch_id: str) -> Any:
        return self._client.batches.retrieve(batch_id)

    def results(self, batch_id: str, batch: Any | None = None) -> list[Any]:
        active_batch = batch or self.retrieve(batch_id)
        normalized = _normalize(active_batch)
        file_ids = [
            _field(normalized, active_batch, "output_file_id"),
            _field(normalized, active_batch, "error_file_id"),
        ]
        items: list[Any] = []
        for file_id in file_ids:
            if not isinstance(file_id, str) or not file_id:
                continue
            content = self._client.files.content(file_id)
            text = _response_content_text(content)
            items.extend(json.loads(line) for line in text.splitlines() if line.strip())
        return items


class GeminiEvaluationBatchClient:
    provider = "google"

    def __init__(self, *, api_key: str | None = None) -> None:
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Gemini SDK is not installed.") from exc
        self._client = genai.Client(api_key=api_key)

    def submit(self, jobs: list[EvaluationJob]) -> Any:
        return self._client.batches.create(
            model=jobs[0].judge.model,
            src=[_gemini_inlined_request(job) for job in jobs],
            config={"display_name": f"{jobs[0].result.experimentId}-{judge_identifier(jobs[0].judge)}"},
        )

    def retrieve(self, batch_id: str) -> Any:
        return self._client.batches.get(name=batch_id)

    def results(self, batch_id: str, batch: Any | None = None) -> list[Any]:
        active_batch = batch or self.retrieve(batch_id)
        normalized = _normalize(active_batch)
        responses = _field(normalized.get("dest") if isinstance(normalized, dict) else None, getattr(active_batch, "dest", None), "inlined_responses")
        if responses is None:
            responses = _field(normalized.get("dest") if isinstance(normalized, dict) else None, getattr(active_batch, "dest", None), "inlinedResponses")
        return responses if isinstance(responses, list) else []


def batch_manifest_path(source_root: Path) -> Path:
    return source_root / EVALUATION_BATCH_MANIFEST


def submit_evaluation_batch(
    *,
    jobs: list[EvaluationJob],
    source_root: Path,
    client: Any | None = None,
) -> dict[str, Any]:
    if not jobs:
        raise ValueError("No evaluation jobs to submit.")
    _ensure_single_batch_judge(jobs)
    active_client = client or _client_for_job(jobs[0])
    batch = active_client.submit(jobs)
    manifest = _build_manifest(batch, jobs=jobs, status="submitted")
    write_json(batch_manifest_path(source_root), manifest)
    return manifest


def retrieve_evaluation_batch(
    *,
    batch_id: str,
    jobs: list[EvaluationJob],
    source_root: Path,
    wait: bool = False,
    poll_interval: int = DEFAULT_BATCH_POLL_INTERVAL_SECONDS,
    client: Any | None = None,
) -> tuple[dict[str, Any], list[EvaluationTrialResult]]:
    if not jobs:
        raise ValueError("No evaluation jobs available for batch retrieval.")
    _ensure_single_batch_judge(jobs)
    active_client = client or _client_for_job(jobs[0])
    batch = active_client.retrieve(batch_id)
    while wait and not _is_terminal_status(batch):
        sleep(max(1, poll_interval))
        batch = active_client.retrieve(batch_id)

    manifest = _build_manifest(batch, jobs=jobs, status=_processing_status(batch) or "unknown")
    write_json(batch_manifest_path(source_root), manifest)
    if not _is_success_status(batch):
        return manifest, []

    results = _evaluation_results_from_batch(active_client.results(batch_id, batch), jobs)
    manifest["status"] = "completed"
    manifest["completedTrialCount"] = len(results)
    write_json(batch_manifest_path(source_root), manifest)
    return manifest, results


def load_batch_id_from_manifest(source_root: Path) -> str | None:
    path = batch_manifest_path(source_root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    value = payload.get("batchId") if isinstance(payload, dict) else None
    return value if isinstance(value, str) and value else None


def _client_for_job(job: EvaluationJob) -> Any:
    api_key = job.judge.params.get("api_key")
    provider = job.judge.provider.lower()
    key = api_key if isinstance(api_key, str) else None
    if provider.startswith("anthropic") or provider.startswith("claude"):
        return AnthropicEvaluationBatchClient(api_key=key)
    if provider.startswith("openai"):
        return OpenAIEvaluationBatchClient(api_key=key)
    if provider.startswith("google") or provider.startswith("gemini"):
        return GeminiEvaluationBatchClient(api_key=key)
    raise ValueError(f"Batch evaluation is not supported for provider {job.judge.provider}.")


def _ensure_single_batch_judge(jobs: list[EvaluationJob]) -> None:
    judges = {(job.judge.provider, job.judge.model, judge_identifier(job.judge)) for job in jobs}
    if len(judges) != 1:
        raise ValueError("Batch evaluation currently requires exactly one selected judge.")
    provider = jobs[0].judge.provider.lower()
    if not (
        provider.startswith("anthropic")
        or provider.startswith("claude")
        or provider.startswith("openai")
        or provider.startswith("google")
        or provider.startswith("gemini")
    ):
        raise ValueError(f"Batch evaluation is not supported for provider {jobs[0].judge.provider}.")


def _anthropic_batch_request(job: EvaluationJob) -> dict[str, Any]:
    params = dict(job.judge.params)
    structured_output = params.pop("structured_output", None)
    params.pop("id", None)
    params.pop("judgeId", None)
    params.pop("judge_id", None)
    params.pop("name", None)
    params.pop("api_key", None)
    payload: dict[str, Any] = {
        "model": job.judge.model,
        "system": EVALUATION_SYSTEM_INSTRUCTION,
        "messages": [{"role": "user", "content": job.prompt}],
        "max_tokens": params.pop("max_tokens", params.pop("max_output_tokens", 1024)),
    }
    if job.judge.temperature is not None:
        payload["temperature"] = job.judge.temperature
    payload.update(params)
    if not isinstance(structured_output, dict):
        structured_output = {
            "name": "judge_response",
            "strict": True,
            "schema": JUDGE_STRUCTURED_OUTPUT_SCHEMA,
        }
    schema = structured_output.get("schema")
    if isinstance(schema, dict):
        payload["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    return {
        "custom_id": job.custom_id,
        "params": payload,
    }


def _openai_batch_request(job: EvaluationJob) -> dict[str, Any]:
    params = dict(job.judge.params)
    structured_output = params.pop("structured_output", None)
    params.pop("id", None)
    params.pop("judgeId", None)
    params.pop("judge_id", None)
    params.pop("name", None)
    params.pop("api_key", None)
    body: dict[str, Any] = {
        "model": job.judge.model,
        "instructions": EVALUATION_SYSTEM_INSTRUCTION,
        "input": job.prompt,
    }
    max_tokens = params.pop("max_tokens", params.pop("max_output_tokens", 1024))
    if max_tokens is not None:
        body["max_output_tokens"] = max_tokens
    body.update(params)
    if not isinstance(structured_output, dict):
        structured_output = {
            "name": "judge_response",
            "strict": True,
            "schema": JUDGE_STRUCTURED_OUTPUT_SCHEMA,
        }
    schema = structured_output.get("schema")
    if isinstance(schema, dict):
        body["text"] = {
            "format": {
                "type": "json_schema",
                "name": str(structured_output.get("name") or "judge_response"),
                "strict": bool(structured_output.get("strict", True)),
                "schema": schema,
            }
        }
    return {
        "custom_id": job.custom_id,
        "method": "POST",
        "url": "/v1/responses",
        "body": body,
    }


def _gemini_inlined_request(job: EvaluationJob) -> Any:
    try:
        from google.genai import types
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Gemini SDK is not installed.") from exc
    config = _gemini_generation_config(job)
    return types.InlinedRequest(
        model=job.judge.model,
        contents=job.prompt,
        metadata={"custom_id": job.custom_id},
        config=types.GenerateContentConfig(**config),
    )


def _gemini_generation_config(job: EvaluationJob) -> dict[str, Any]:
    params = dict(job.judge.params)
    structured_output = params.pop("structured_output", None)
    params.pop("id", None)
    params.pop("judgeId", None)
    params.pop("judge_id", None)
    params.pop("name", None)
    params.pop("api_key", None)
    config: dict[str, Any] = {"system_instruction": EVALUATION_SYSTEM_INSTRUCTION}
    if job.judge.temperature is not None:
        config["temperature"] = job.judge.temperature
    max_tokens = params.pop("max_tokens", params.pop("max_output_tokens", 1024))
    if max_tokens is not None:
        config["max_output_tokens"] = max_tokens
    config.update(params)
    if not isinstance(structured_output, dict):
        structured_output = {"schema": JUDGE_STRUCTURED_OUTPUT_SCHEMA}
    schema = structured_output.get("schema")
    if isinstance(schema, dict):
        config["response_mime_type"] = "application/json"
        config["response_json_schema"] = schema
    return config


def _evaluation_results_from_batch(items: list[Any], jobs: list[EvaluationJob]) -> list[EvaluationTrialResult]:
    jobs_by_custom_id = {job.custom_id: job for job in jobs}
    evaluations: list[EvaluationTrialResult] = []
    for item in items:
        payload = _normalize(item)
        if not isinstance(payload, dict):
            continue
        custom_id = _custom_id_from_payload(payload)
        if not isinstance(custom_id, str) or custom_id not in jobs_by_custom_id:
            continue
        job = jobs_by_custom_id[custom_id]
        provider = job.judge.provider.lower()
        if provider.startswith("openai"):
            evaluated = _openai_evaluation_from_payload(job, payload, custom_id)
        elif provider.startswith("google") or provider.startswith("gemini"):
            evaluated = _gemini_evaluation_from_payload(job, payload, custom_id)
        else:
            evaluated = _anthropic_evaluation_from_payload(job, payload, custom_id)
        evaluations.append(evaluated)
    return evaluations


def _anthropic_evaluation_from_payload(job: EvaluationJob, payload: dict[str, Any], custom_id: str) -> EvaluationTrialResult:
    result = payload.get("result")
    if not isinstance(result, dict):
        return _failed_evaluation(job, payload, "Batch result is missing a result payload.")
    result_type = result.get("type")
    if result_type != "succeeded":
        return _failed_evaluation(job, payload, f"Batch request {result_type or 'failed'}.")
    message = result.get("message")
    if not isinstance(message, dict):
        return _failed_evaluation(job, payload, "Batch result is missing a message.")
    text = _extract_anthropic_message_text(message)
    judge_payload = _parse_json_payload(text)
    usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
    return evaluation_from_judge_payload(
        job,
        payload=judge_payload,
        judge_info=EvaluationJudgeInfo(
            used=True,
            role="judge",
            provider=job.judge.provider,
            model=job.judge.model,
            inputTokens=_as_int(usage.get("input_tokens")),
            outputTokens=_as_int(usage.get("output_tokens")),
            durationMs=None,
        ),
        trace=EvaluationTrace(
            aiTrace={"batch": {"customId": custom_id, "resultType": result_type}},
            rawResponse=payload,
        ),
    )


def _openai_evaluation_from_payload(job: EvaluationJob, payload: dict[str, Any], custom_id: str) -> EvaluationTrialResult:
    error = payload.get("error")
    if error:
        return _failed_evaluation(job, payload, "Batch request errored.")
    response = payload.get("response")
    if not isinstance(response, dict):
        return _failed_evaluation(job, payload, "Batch result is missing a response payload.")
    status_code = response.get("status_code")
    body = response.get("body")
    if status_code and status_code >= 400:
        return _failed_evaluation(job, payload, f"Batch request failed with status {status_code}.")
    if not isinstance(body, dict):
        return _failed_evaluation(job, payload, "Batch response is missing a body.")
    text = _extract_openai_response_text(body)
    judge_payload = _parse_json_payload(text)
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    return evaluation_from_judge_payload(
        job,
        payload=judge_payload,
        judge_info=EvaluationJudgeInfo(
            used=True,
            role="judge",
            provider=job.judge.provider,
            model=job.judge.model,
            inputTokens=_as_int(usage.get("input_tokens")),
            outputTokens=_as_int(usage.get("output_tokens")),
            durationMs=None,
        ),
        trace=EvaluationTrace(
            aiTrace={"batch": {"customId": custom_id, "statusCode": status_code}},
            rawResponse=payload,
        ),
    )


def _gemini_evaluation_from_payload(job: EvaluationJob, payload: dict[str, Any], custom_id: str) -> EvaluationTrialResult:
    error = payload.get("error")
    if error:
        return _failed_evaluation(job, payload, "Batch request errored.")
    response = payload.get("response") if isinstance(payload.get("response"), dict) else payload
    text = _extract_gemini_response_text(response)
    judge_payload = _parse_json_payload(text)
    usage = response.get("usage_metadata") if isinstance(response.get("usage_metadata"), dict) else response.get("usageMetadata")
    usage = usage if isinstance(usage, dict) else {}
    return evaluation_from_judge_payload(
        job,
        payload=judge_payload,
        judge_info=EvaluationJudgeInfo(
            used=True,
            role="judge",
            provider=job.judge.provider,
            model=job.judge.model,
            inputTokens=_as_int(usage.get("prompt_token_count") or usage.get("promptTokenCount")),
            outputTokens=_as_int(usage.get("candidates_token_count") or usage.get("candidatesTokenCount")),
            durationMs=None,
        ),
        trace=EvaluationTrace(
            aiTrace={"batch": {"customId": custom_id}},
            rawResponse=payload,
        ),
    )


def _custom_id_from_payload(payload: dict[str, Any]) -> str | None:
    value = payload.get("custom_id") or payload.get("customId")
    if isinstance(value, str):
        return value
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("custom_id") or metadata.get("customId")
        if isinstance(value, str):
            return value
    return None


def _parse_json_payload(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text.strip())
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _extract_openai_response_text(body: dict[str, Any]) -> str:
    text = body.get("output_text")
    if isinstance(text, str):
        return text.strip()
    output = body.get("output")
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "\n".join(parts).strip()


def _extract_gemini_response_text(response: dict[str, Any]) -> str:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return ""
    text_parts = [part.get("text") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)]
    return "\n".join(text_parts).strip()


def _failed_evaluation(job: EvaluationJob, raw_response: dict[str, Any], error: str) -> EvaluationTrialResult:
    return evaluation_from_judge_payload(
        job,
        payload=None,
        judge_info=EvaluationJudgeInfo(
            used=True,
            role="judge",
            provider=job.judge.provider,
            model=job.judge.model,
        ),
        trace=EvaluationTrace(
            aiTrace={"batch": {"customId": job.custom_id}},
            rawResponse=raw_response,
            error=error,
        ),
    )


def _extract_anthropic_message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts).strip()


def _build_manifest(batch: Any, *, jobs: list[EvaluationJob], status: str) -> dict[str, Any]:
    normalized = _normalize(batch)
    batch_id = _field(normalized, batch, "id") or _field(normalized, batch, "name")
    processing_status = _field(normalized, batch, "processing_status")
    if processing_status is None:
        processing_status = _field(normalized, batch, "status") or _field(normalized, batch, "state")
    results_url = _field(normalized, batch, "results_url")
    return {
        "kind": "evaluation_batch",
        "experimentId": jobs[0].result.experimentId,
        "provider": jobs[0].judge.provider,
        "model": jobs[0].judge.model,
        "judgeId": judge_identifier(jobs[0].judge),
        "batchId": batch_id,
        "status": status,
        "processingStatus": processing_status,
        "resultsUrl": results_url,
        "outputFileId": _field(normalized, batch, "output_file_id"),
        "errorFileId": _field(normalized, batch, "error_file_id"),
        "requestCount": len(jobs),
        "requestCounts": _field(normalized, batch, "request_counts"),
        "errors": _field(normalized, batch, "errors"),
        "completionStats": _field(normalized, batch, "completion_stats") or _field(normalized, batch, "completionStats"),
        "requests": [
            {
                "customId": job.custom_id,
                "trialId": job.result.trialId,
                "taskId": job.result.taskId,
                "instanceId": job.result.instanceId,
            }
            for job in jobs
        ],
    }


def _processing_status(batch: Any) -> str | None:
    normalized = _normalize(batch)
    value = _field(normalized, batch, "processing_status") or _field(normalized, batch, "status") or _field(normalized, batch, "state")
    return value if isinstance(value, str) else None


def _is_terminal_status(batch: Any) -> bool:
    status = (_processing_status(batch) or "").lower()
    return status in {
        "ended",
        "completed",
        "failed",
        "expired",
        "cancelled",
        "canceled",
        "job_state_succeeded",
        "job_state_failed",
        "job_state_cancelled",
        "job_state_expired",
        "job_state_partially_succeeded",
    }


def _is_success_status(batch: Any) -> bool:
    status = (_processing_status(batch) or "").lower()
    return status in {"ended", "completed", "job_state_succeeded", "job_state_partially_succeeded"}


def _field(normalized: Any, source: Any, name: str) -> Any:
    if isinstance(normalized, dict) and name in normalized:
        return normalized.get(name)
    return getattr(source, name, None)


def _response_content_text(content: Any) -> str:
    if hasattr(content, "text") and isinstance(content.text, str):
        return content.text
    if hasattr(content, "read"):
        value = content.read()
        if isinstance(value, bytes):
            return value.decode("utf-8")
        if isinstance(value, str):
            return value
    if isinstance(content, bytes):
        return content.decode("utf-8")
    if isinstance(content, str):
        return content
    return str(content)


def _normalize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if hasattr(value, "__dict__"):
        return {
            key: _normalize(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return value


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
