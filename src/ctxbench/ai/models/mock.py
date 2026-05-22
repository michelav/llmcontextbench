from __future__ import annotations

import json
import re

from ctxbench.ai.models.base import AIRequest, ModelAdapter, ModelInput, ModelResponse


class MockModel(ModelAdapter):
    name = "mock"

    def generate(self, model_input: ModelInput, request: AIRequest, trace: object | None = None) -> ModelResponse:
        task_id = request.task_id() or ""
        answer = self._extract_answer(request.context, task_id)
        input_tokens = len(model_input.prompt.split())
        output_tokens = len(answer.split())
        return ModelResponse(
            text=answer,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            duration_ms=0,
            raw_response={
                "system_instruction_preview": model_input.system_instruction[:200],
                "prompt_preview": model_input.prompt[:200],
            },
            metadata={"provider": "mock"},
        )

    def _extract_answer(self, context: str, task_id: str) -> str:
        try:
            payload = json.loads(context)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            answers = payload.get("answers")
            if isinstance(answers, dict):
                value = answers.get(task_id)
                if value is not None:
                    return str(value)
        for pattern in [
            rf"^{re.escape(task_id)}\s*=\s*(.+)$",
            rf"^ANSWER\[{re.escape(task_id)}\]\s*:\s*(.+)$",
            r"^ANSWER\s*:\s*(.+)$",
        ]:
            match = re.search(pattern, context, flags=re.MULTILINE)
            if match:
                return match.group(1).strip()
        return "Not enough information."
