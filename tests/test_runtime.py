from __future__ import annotations

import subprocess
import sys

import pytest

from ctxbench.ai.engine import Engine
from ctxbench.core.provisioning import ProvisioningConfiguration
from ctxbench.runtime import ProvisioningRuntime, RuntimeRequest


class ContextValue:
    def __init__(self, content: object) -> None:
        self.content = content


class InMemoryContextSource:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def get_context(self, instance_id: str, task_id: str, representation: str) -> ContextValue:
        self.calls.append((instance_id, task_id, representation))
        return ContextValue({"answers": {"q1": "runtime answer"}})


def test_runtime_executes_inline_without_benchmark_records() -> None:
    source = InMemoryContextSource()
    request = RuntimeRequest(
        task="What is the answer?",
        task_id="q1",
        instance_id="instance-1",
        provider="mock",
        model_name="mock",
        configuration=ProvisioningConfiguration(
            strategy="inline",
            representation="json",
            surface="full",
        ),
        surface_spec={"type": "full_context"},
        params={},
        metadata={"taskId": "q1"},
    )

    result = ProvisioningRuntime(Engine(), source).execute(request)

    assert result.ai_result.answer == "runtime answer"
    assert result.ai_result.error is None
    assert source.calls == [("instance-1", "q1", "json")]
    assert result.duration_ms >= 0


def test_runtime_requires_tool_capability() -> None:
    request = RuntimeRequest(
        task="Task",
        task_id="q1",
        instance_id="instance-1",
        provider="mock",
        model_name="mock",
        configuration=ProvisioningConfiguration(
            strategy="local_function",
            representation="json",
            surface="ops",
        ),
        surface_spec={"type": "operations", "operations": ["lookup"]},
        params={},
    )

    with pytest.raises(ValueError, match="tool_provider capability"):
        ProvisioningRuntime(Engine(), InMemoryContextSource()).execute(request)


def test_runtime_package_has_no_transitive_benchmark_import() -> None:
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import ctxbench.runtime; "
            "assert not any(name == 'ctxbench.benchmark' or name.startswith('ctxbench.benchmark.') for name in sys.modules)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert process.returncode == 0, process.stderr


def test_adapter_typeerror_is_not_retried_without_operation_restrictions():
    class BrokenTools(InMemoryContextSource):
        calls_count = 0

        def tool_provider(self, *, allowed_operations=None):
            self.calls_count += 1
            assert allowed_operations == ['lookup']
            raise TypeError('adapter implementation defect')

    source = BrokenTools()
    request = RuntimeRequest(task='task', task_id='t', instance_id='i', provider='mock', model_name='mock',
                             configuration=ProvisioningConfiguration(strategy='local_function', representation='json', surface='ops'),
                             surface_spec={'operations': ['lookup']}, params={})
    with pytest.raises(TypeError, match='adapter implementation defect'):
        ProvisioningRuntime(Engine(), source).execute(request)
    assert source.calls_count == 1


def test_runtime_measures_elapsed_time_including_context_preparation():
    ticks = iter([10.0, 10.125])
    request = RuntimeRequest(task='task', task_id='q1', instance_id='i', provider='mock', model_name='mock',
                             configuration=ProvisioningConfiguration(strategy='inline', representation='json', surface='full'),
                             surface_spec={}, params={}, metadata={'taskId': 'q1'})
    result = ProvisioningRuntime(Engine(), InMemoryContextSource(), monotonic=lambda: next(ticks)).execute(request)
    assert result.duration_ms == 125
