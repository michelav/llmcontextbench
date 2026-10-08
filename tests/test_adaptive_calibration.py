from dataclasses import asdict
import runpy

import pytest

from ctxbench.adaptive.calibration import DelayedRuntime, delay_at, freeze_calibration, load_estimates, quantile
from ctxbench.adaptive.types import Observation, SizeBin, TokenUsage, Provenance
from ctxbench.benchmark.executor import _build_tool_runtime_factories


def packets(local_duration=100):
    rows = []
    for cid in ('inline-code-full', 'local-mcp-repoqa-ops'):
        for size in SizeBin:
            for _ in range(16):
                observation = Observation(cid, size, 'success', local_duration if cid.startswith('local') else 150,
                                          TokenUsage(10, Provenance.REPORTED))
                rows.append({'observation': asdict(observation), 'decision': {'tokens': {'value': 10}}})
    return rows


def test_freeze_delay_quantiles_and_no_qualification():
    baseline = packets()
    delayed = {d: [p for p in packets(120 if d == 100 else 200) if p['observation']['configuration_id'].startswith('local')]
               for d in (100, 250, 500, 1000)}
    frozen = freeze_calibration(baseline, delayed, prepared_hash='fixture')
    assert frozen['latencyObjectiveMs'] == 150
    assert frozen['selectedDelayMs'] == 250
    assert len(load_estimates(frozen)) == 4
    assert quantile([1, 2, 3, 4], .9) == 4
    assert freeze_calibration(baseline, {}, prepared_hash='fixture')['scenarios'] == ['stationary']
    with pytest.raises(ValueError, match='64'):
        freeze_calibration(baseline[:-1], {}, prepared_hash='fixture')


def test_delay_schedule_and_runtime_preservation():
    assert [delay_at(i, 'degradation-recovery', 250) for i in (20, 21, 44, 45)] == [0, 250, 250, 0]
    assert delay_at(30, 'stationary', 250) == 0
    calls = []
    class Runtime:
        def list_tools(self):
            return ['tool']
        def call_tool(self, name, args):
            calls.append((name, args))
            if name == 'error':
                raise RuntimeError('underlying')
            return args
        def close(self):
            calls.append('close')
    wrapper = DelayedRuntime(Runtime(), 250, sleeper=lambda seconds: calls.append(seconds))
    assert wrapper.list_tools() == ['tool']
    assert wrapper.call_tool('tool', {'x': 1}) == {'x': 1}
    with pytest.raises(RuntimeError, match='underlying'):
        wrapper.call_tool('error', {})
    wrapper.close()
    assert calls == [.25, ('tool', {'x': 1}), .25, ('error', {}), 'close']


def test_hook_default_and_failed_decoration_cleanup(monkeypatch):
    class Trial:
        strategy = 'local_mcp'
    class Runtime:
        def close(self):
            closed.append(True)
    closed = []
    monkeypatch.setattr('ctxbench.benchmark.executor.MCPRuntime.for_local_server', lambda server: Runtime())
    factory = _build_tool_runtime_factories(Trial(), dataset_tool_provider=None, dataset_mcp_server=object())['local_mcp']
    assert isinstance(factory(), Runtime)
    def fail(runtime):
        raise RuntimeError('decorator')
    factory = _build_tool_runtime_factories(Trial(), dataset_tool_provider=None, dataset_mcp_server=object(),
                                          local_mcp_runtime_decorator=fail)['local_mcp']
    with pytest.raises(RuntimeError):
        factory()
    assert closed == [True]


def test_research_cli_provider_gate(tmp_path, monkeypatch):
    cli = runpy.run_path('tools/repoqa/run_adaptation.py')
    with pytest.raises(SystemExit):
        cli['main'](['prepare', '--output', str(tmp_path)])
    assert cli['ARMS'] == ('always-inline', 'always-local-mcp', 'frozen-router', 'adaptive-router')
