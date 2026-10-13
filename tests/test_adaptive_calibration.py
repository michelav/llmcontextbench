from dataclasses import asdict
import runpy
from ctxbench.adapters.repoqa import workflow

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


def test_research_cli_required_arguments(tmp_path):
    cli = runpy.run_path('tools/repoqa/run_adaptation.py')
    with pytest.raises(SystemExit):
        cli['main'](['prepare', '--output', str(tmp_path)])
    assert workflow.ARMS == ('always-inline', 'always-local-mcp', 'frozen-router', 'adaptive-router')


def test_counterbalancing_across_seed_scenario_blocks():
    from collections import Counter
    cli = runpy.run_path('tools/repoqa/run_adaptation.py')
    orders = [workflow.policy_order(seed, scenario) for seed in (20261001, 20261002, 20261003)
              for scenario in ('stationary', 'degradation-recovery')]
    for arm in workflow.ARMS:
        positions = Counter(order.index(arm) for order in orders)
        assert set(positions) == {0, 1, 2, 3}
        assert max(positions.values()) - min(positions.values()) <= 1


def test_calibration_provenance_rejects_changed_inputs(tmp_path, monkeypatch):
    from ctxbench.adaptive.recovery import sealed_write
    cli = runpy.run_path('tools/repoqa/run_adaptation.py')
    root = tmp_path / 'always-local-mcp'
    identity = {'catalog': [], 'sources': {}, 'workload': [],
                'metadata': {'datasetProvenance': {'hash': 'expected', 'split': {}},
                             'modelProvenance': {'budget': {}}, 'policy': root.name,
                             'scenario': 'stationary', 'injectionSchedule': [{'start': 1, 'end': 0, 'delayMs': 0}]}}
    sealed_write(root / 'recovery/identity.json', identity)
    study = {'trials': [], 'sources': {}, 'datasetHash': 'expected', 'split': {}, 'budget': {},
             'calibrationOrder': [], 'requests': {}}
    assert workflow.calibration_packets(root, study=study) == []
    study['datasetHash'] = 'changed'
    with pytest.raises(ValueError, match='provenance'):
        workflow.calibration_packets(root, study=study)


@pytest.mark.parametrize('operation', ['calibrate', 'episode'])
@pytest.mark.parametrize('scorer_fails', [False, True])
def test_research_cli_executes_without_authorization_flag(operation, scorer_fails, tmp_path, monkeypatch, capsys):
    from tests.test_adaptive_runner import episode as episode_fixture
    from ctxbench.adapters.repoqa.study import digest
    from ctxbench.adaptive.recovery import sealed_write

    trials, _, _ = episode_fixture.__wrapped__(tmp_path)
    trials = [t.model_copy(update={'provider': 'openai'}) for t in trials[:2]]
    sources = {'revision': 'fixture'}
    study = {'trials': [t.model_dump(mode='json') for t in trials], 'sources': sources,
             'datasetHash': 'fixture', 'split': {}, 'budget': {},
             'calibrationOrder': [], 'heldOut': {'20261001': []}, 'requests': {}}
    prepared = tmp_path / 'prepared.json'
    sealed_write(prepared, study)
    sealed_write(tmp_path / 'frozen.json', {
        'preparedHash': digest(study), 'sources': sources, 'baselineHash': digest([]),
        'delayHashes': {str(d): digest([]) for d in (100, 250, 500, 1000)},
        'scenarios': ['stationary'], 'selectedDelayMs': None, 'latencyObjectiveMs': 100})
    cli = runpy.run_path('tools/repoqa/run_adaptation.py')
    scope = vars(workflow)
    events = []
    monkeypatch.setitem(scope, 'verify_study', lambda study: events.append('verified'))
    monkeypatch.setitem(scope, 'source_identity', lambda: sources)
    monkeypatch.setitem(scope, 'frozen_inputs', lambda *args: ([], {d: [] for d in (100, 250, 500, 1000)}))
    monkeypatch.setitem(scope, 'load_estimates', lambda frozen: {})
    def scorer():
        events.append('scored')
        if scorer_fails:
            raise RuntimeError('scorer failed')
    monkeypatch.setitem(scope, 'scorer_smoke', scorer)
    class Engine:
        def __init__(self):
            events.append('engine')
        def close(self):
            events.append('closed')
    monkeypatch.setattr('ctxbench.ai.engine.Engine', Engine)
    def execute(*args, **kwargs):
        events.append(args[3])
        assert kwargs['resume'] is False
        assert kwargs['retry_uncertain'] is False
        return []
    monkeypatch.setitem(scope, 'run_episode', execute)
    argv = [operation, '--prepared', str(prepared), '--output', str(tmp_path)]
    if operation == 'episode':
        argv += ['--policy', 'all', '--scenario', 'stationary']
    if scorer_fails:
        assert cli['main'](argv) == 1
        assert events == ['verified', 'scored']
    else:
        assert cli['main'](argv) == 0
        arms = list(workflow.ARMS) if operation == 'episode' else list(workflow.ARMS[:2])
        assert events == ['verified', 'scored', 'engine', *arms, 'closed']
    assert 'Provider execution spends API tokens' in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:
        cli['main'](argv + ['--execute-providers'])
    assert exc.value.code == 2
