"""One execution path for context provisioning, independent of benchmark artifacts."""
from __future__ import annotations

import json
from time import perf_counter

from ctxbench.ai.cache import build_inline_prompt_cache_key
from ctxbench.ai.engine import Engine
from ctxbench.ai.models.base import AIRequest, AIResult
from ctxbench.ai.runtime import LocalFunctionRuntime, MCPRuntime
from ctxbench.core.errors import CapabilityUnavailableError
from ctxbench.runtime.models import ContextSource, ExecutionResult, RuntimeRequest
from ctxbench.util.clock import utc_now_iso
from ctxbench.util.env import redact_secrets, resolve_secret_params


class ProvisioningRuntime:
    def __init__(self, engine: Engine, context_source: ContextSource, *,
                 local_mcp_runtime_decorator=None, monotonic=perf_counter) -> None:
        self._engine = engine
        self._context_source = context_source
        self._decorate = local_mcp_runtime_decorator
        self._monotonic = monotonic

    def execute(self, request: RuntimeRequest) -> ExecutionResult:
        started_at = utc_now_iso()
        start = self._monotonic()
        strategy = request.configuration.strategy
        context = ""
        params, secrets = resolve_secret_params(dict(request.params))
        if strategy == "inline":
            payload = self._context_source.get_context(request.instance_id, request.task_id,
                                                      request.configuration.representation)
            context = _context_to_text(payload.content)
            if request.provider.lower().startswith("openai"):
                params.setdefault("prompt_cache_key", build_inline_prompt_cache_key(
                    model_name=request.cache_model_name or request.model_name,
                    instance_id=request.instance_id, representation=request.configuration.representation,
                    context=context))
        factories = {}
        operations = request.surface_spec.get("operations")
        if strategy == "local_function":
            provider = self._capability("tool_provider", operations)
            factories[strategy] = lambda: _decorate_runtime(LocalFunctionRuntime(provider), self._decorate)
        elif strategy == "local_mcp":
            server = self._capability("mcp_server", operations)
            factories[strategy] = lambda: create_local_mcp_runtime(server, self._decorate)
        elif strategy == "remote_mcp":
            config = params.get("mcp_server")
            if not isinstance(config, dict):
                raise CapabilityUnavailableError("remote_mcp requires execution MCP server settings")
            remote_config = {
                **config,
                "allowed_operations": operations if operations is not None else config.get("allowed_operations"),
            }
            factories[strategy] = lambda: _decorate_runtime(MCPRuntime.from_config(remote_config), self._decorate)

        metadata = {**request.metadata, "instance_id": request.instance_id,
                    "context_obtained": strategy == "inline"}
        instructions = getattr(self._context_source, "dataset_instructions", lambda: None)()
        if instructions:
            metadata["dataset_instructions"] = instructions
        ai_request = AIRequest(question=request.task, context=context, provider_name=request.provider,
                               model_name=request.model_name, strategy_name=strategy,
                               context_representation=request.configuration.representation,
                               params=params, metadata=metadata)
        owned = self._engine.copy_with_tool_runtime_factories(factories) if factories else None
        try:
            result = (owned or self._engine).execute(ai_request)
        finally:
            if owned is not None:
                owned.close()
        if secrets:
            result = AIResult.model_validate(redact_secrets(result.model_dump(), secrets))
        return ExecutionResult(ai_result=result, started_at=started_at, finished_at=utc_now_iso(),
                               duration_ms=max(0, int((self._monotonic() - start) * 1000)))

    def _capability(self, name: str, operations):
        method = getattr(self._context_source, name, None)
        if method is None:
            raise CapabilityUnavailableError(f"Dataset requires {name} capability")
        # Signature inspection avoids hiding a TypeError raised inside an adapter.
        from inspect import signature
        kwargs = {"allowed_operations": operations} if "allowed_operations" in signature(method).parameters else {}
        value = method(**kwargs)
        if value is None:
            raise CapabilityUnavailableError(f"Dataset requires {name} capability")
        return value


def _context_to_text(content: object) -> str:
    return content if isinstance(content, str) else json.dumps(content)


def create_local_mcp_runtime(server, decorator=None):
    """Transfer ownership only after successful decoration."""
    runtime = MCPRuntime.for_local_server(server)
    if decorator is None:
        return runtime
    try:
        return decorator(runtime)
    except BaseException:
        runtime.close()
        raise


def _decorate_runtime(runtime, decorator=None):
    if decorator is None:
        return runtime
    try:
        return decorator(runtime)
    except BaseException:
        runtime.close()
        raise
