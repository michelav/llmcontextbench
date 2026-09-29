"""Execution of a single context-provisioning request."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ctxbench.ai.cache import build_inline_prompt_cache_key
from ctxbench.ai.engine import Engine
from ctxbench.ai.models.base import AIRequest
from ctxbench.runtime.models import ContextSource, ExecutionResult, RuntimeRequest
from ctxbench.util.clock import utc_now_iso


class ProvisioningRuntime:
    def __init__(self, engine: Engine, context_source: ContextSource) -> None:
        self._engine = engine
        self._context_source = context_source

    def execute(self, request: RuntimeRequest) -> ExecutionResult:
        if request.configuration.strategy != "inline":
            raise ValueError(
                "ProvisioningRuntime currently supports only the inline strategy."
            )

        context_payload = self._context_source.get_context(
            request.instance_id,
            request.task_id,
            request.configuration.representation,
        )
        context = _context_to_text(context_payload.content)
        params = dict(request.params)
        if request.provider.lower().startswith("openai"):
            params.setdefault(
                "prompt_cache_key",
                build_inline_prompt_cache_key(
                    model_name=request.cache_model_name or request.model_name,
                    instance_id=request.instance_id,
                    representation=request.configuration.representation,
                    context=context,
                ),
            )
        metadata = dict(request.metadata)
        dataset_instructions = getattr(self._context_source, "dataset_instructions", lambda: None)()
        if dataset_instructions:
            metadata["dataset_instructions"] = dataset_instructions
        ai_request = AIRequest(
            question=request.task,
            context=context,
            provider_name=request.provider,
            model_name=request.model_name,
            strategy_name=request.configuration.strategy,
            context_representation=request.configuration.representation,
            params=params,
            metadata=metadata,
        )
        started_at = utc_now_iso()
        start = _parse_iso(started_at)
        ai_result = self._engine.execute(ai_request)
        finished_at = utc_now_iso()
        finish = _parse_iso(finished_at)
        return ExecutionResult(
            ai_result=ai_result,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=max(0, int((finish - start).total_seconds() * 1000)),
        )


def _context_to_text(content: object) -> str:
    return content if isinstance(content, str) else json.dumps(content)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
