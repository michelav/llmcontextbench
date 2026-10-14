import json
from pathlib import Path

import pytest

from ctxbench.studies import baseline, study
from ctxbench.studies.models import Study
from ctxbench.adaptive.recovery import sealed_read
from ctxbench.adaptive.runner import error_result
from ctxbench.adaptive.study_policy import Controller


def mock_execute(trial, engine, **kwargs):
    result = error_result(trial, 'fixture', '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z', 100)
    return result.model_copy(update={'status': 'success', 'errorMessage': None, 'response': 'code',
                                     'usage': {'totalTokens': 10}})


@pytest.fixture
def frozen(tmp_path):
    payload = json.loads(Path('tests/fixtures/repoqa_surface_experiment.json').read_text())
    payload['dataset']['root'] = str(Path('datasets/repoqa').resolve())
    payload['scope']['instances'] = []
    payload['execution'] = {'repeats': 1}
    (tmp_path / 'experiment.json').write_text(json.dumps(payload))
    (tmp_path / 'baseline.json').write_text(json.dumps({'experiment':'experiment.json',
        'split': {'seed':42, 'calibrationTargetsPerLanguage':1}, 'seeds':[1], 'repeats':1,
        'contextLimit':200000, 'outputReservation':2048}))
    prepared = baseline.prepare(definition=tmp_path / 'baseline.json', output=tmp_path / 'baseline')['prepared']
    baseline.execute(prepared=prepared, execution=mock_execute)
    return Path(baseline.freeze(prepared=prepared)['frozen'])


def make_study(tmp_path, frozen, **overrides):
    definition = {'baseline': str(frozen), 'seeds':[201], 'repeats':1,
        'policies': {'fixed': {'type':'fixed','configuration':'inline-code-full'},
                     'router': {'type':'router','adaptive':True}},
        'latencyLimitMs': 1000, 'scenarios': {'stationary': []},
        'comparisons':[['router','fixed']]}
    definition.update(overrides)
    path = tmp_path / ('definition-'+str(len(list(tmp_path.glob('definition-*'))))+'.json')
    path.write_text(json.dumps(definition))
    return path


def test_study_reuse_matrix_execution_and_status(frozen, tmp_path):
    definition = make_study(tmp_path, frozen)
    first = Path(study.prepare(definition=definition, output=tmp_path/'study-one')['prepared'])
    second = Path(study.prepare(definition=definition, output=tmp_path/'study-two')['prepared'])
    a, b = sealed_read(first), sealed_read(second)
    assert a['baselineDigest'] == b['baselineDigest']
    assert len(a['episodes']) == 2
    assert a['episodes'][0]['workload'] == a['episodes'][1]['workload']
    assert study.status(first)['matrix'][0]['completed'] == 0
    e = a['episodes'][0]
    study.episode(prepared=first, policy=e['policyName'], scenario='stationary', seed=201, repeat=1,
                  execution=mock_execute)
    status = study.status(first)['matrix']
    assert sorted(row['completed'] for row in status) == [0, 64]
    study.episode(prepared=first, policy=e['policyName'], scenario='stationary', seed=201, repeat=1,
                  resume=True, execution=lambda *a, **kw: pytest.fail('reran completed call'))


def test_rejects_incompatible_and_invalid_studies(frozen, tmp_path):
    with pytest.raises(ValueError, match='routing requires'):
        Study.model_validate({'baseline':str(frozen), 'seeds':[1], 'repeats':1,
            'policies':{'r':{'type':'router','adaptive':True}}, 'scenarios':{'stationary':[]}})
    bad = make_study(tmp_path, frozen, scenarios={'delayed':[{'configuration':'inline-code-full',
        'scope':'tool-call','delayMs':5,'firstRequest':1,'lastRequest':3}]})
    with pytest.raises(ValueError, match='tool-call delay'):
        study.prepare(definition=bad, output=tmp_path/'bad-study')
    bad = make_study(tmp_path, frozen, configurations=['missing'])
    with pytest.raises(ValueError, match='unknown configuration'):
        study.prepare(definition=bad, output=tmp_path/'bad-study2')


def test_controller_budget_and_reliability(frozen, tmp_path):
    definition = make_study(tmp_path, frozen, policies={'budget':{'type':'budget','probeInterval':100},
                                      'inline':{'type':'fixed','configuration':'inline-code-full'},
                                      'mcp':{'type':'fixed','configuration':'local-mcp-repoqa-ops'}},
                            latencyLimitMs=None, tokenBudget=700, comparisons=[])
    path = Path(study.prepare(definition=definition, output=tmp_path/'budget-study')['prepared'])
    plan = sealed_read(path)
    controller = Controller(plan, plan['episodes'][0])
    assert controller.decide(0)['configuration'] in plan['configurations']
    controller.observe({'configuration':plan['configurations'][0], 'sizeBin':'small', 'status':'success',
                        'durationMs':10, 'tokens':{'value':None,'knownPartial':5}, 'failures':[], 'sequenceIndex':1})
    assert controller.decide(1)['configuration'] is None
    assert controller.ledger()['unknownConsumption'] is True


def test_source_drift_allowed_only_for_read_only_commands(frozen, tmp_path, monkeypatch):
    definition = make_study(tmp_path, frozen)
    path = Path(study.prepare(definition=definition, output=tmp_path/'study-drift')['prepared'])
    original = baseline.measurement_sources()
    drifted = {**original, 'files': {**original['files'], 'src/ctxbench/adaptive/study_runner.py': 'changed'}}
    monkeypatch.setattr(baseline, 'measurement_sources', lambda: drifted)
    with pytest.raises(ValueError, match='measurement source fingerprint mismatch'):
        study.status(path)
    with pytest.raises(ValueError, match='measurement source fingerprint mismatch'):
        study.analyze(path, bootstrap_replicates=10)
    assert study.status(path, allow_source_drift=True)['sourceDrift'] == ['src/ctxbench/adaptive/study_runner.py']
    report = study.analyze(path, bootstrap_replicates=10, allow_source_drift=True)
    assert report['sourceDrift'] == ['src/ctxbench/adaptive/study_runner.py']
    assert json.loads((path.parent/'analysis.json').read_text())['sourceDrift'] == report['sourceDrift']
    with pytest.raises(ValueError, match='measurement source fingerprint mismatch'):
        study.episode(prepared=path, policy='fixed', scenario='stationary', seed=201, repeat=1,
                      execution=mock_execute)
    with pytest.raises(ValueError, match='measurement source fingerprint mismatch'):
        study.prepare(definition=definition, output=tmp_path/'study-drift-new')


def test_no_source_drift_key_without_drift(frozen, tmp_path):
    path = Path(study.prepare(definition=make_study(tmp_path, frozen), output=tmp_path/'study-clean')['prepared'])
    assert 'sourceDrift' not in study.status(path, allow_source_drift=True)
    assert 'sourceDrift' not in study.analyze(path, bootstrap_replicates=10)


def test_analysis_incomplete_matrix(frozen, tmp_path):
    definition = make_study(tmp_path, frozen)
    path = Path(study.prepare(definition=definition, output=tmp_path/'study-analysis')['prepared'])
    report = study.analyze(path, bootstrap_replicates=100)
    assert report['plannedEpisodes'] == 2
    assert all(row['completed']==0 for row in report['summaries'])
    assert report['comparisons'][0]['incomplete'] is True
    assert report['comparisons'][0]['meanLatencyDifferenceMs'] is None


def test_request_delay_measured_inside_execution(frozen, tmp_path):
    definition = make_study(tmp_path, frozen,
        policies={'fixed': {'type':'fixed','configuration':'inline-code-full'}}, comparisons=[],
        scenarios={'inline-delay': [{'configuration':'inline-code-full','scope':'request',
                                     'delayMs':500,'firstRequest':1,'lastRequest':1}]})
    path = Path(study.prepare(definition=definition, output=tmp_path/'study-delay')['prepared'])
    class Clock:
        time = 0
        def now(self): return self.time
        def sleep(self, seconds): self.time += seconds
    clock = Clock()
    from ctxbench.adaptive.study_runner import run
    plan = sealed_read(path)
    packet = run(plan, plan['episodes'][0], path.parent/'episodes'/plan['episodes'][0]['id'],
                 monotonic=clock.now, sleeper=clock.sleep, execution=mock_execute)[0]
    assert packet['observation']['durationMs'] >= 500
    assert packet['decision']['delayRequestedMs'] == 500
    assert packet['decision']['delayActualMs'] == 500


def test_reliability_exclusion_cooldown_and_recovery(frozen, tmp_path):
    definition = make_study(tmp_path, frozen, policies={'r': {'type':'reliability',
        'failureClasses':['step-limit'], 'window':3, 'minimumObservations':2,
        'failureRateThreshold':0.5, 'cooldownRequests':2, 'probeInterval':100}}, comparisons=[])
    path = Path(study.prepare(definition=definition, output=tmp_path/'study-reliability')['prepared'])
    plan = sealed_read(path)
    controller = Controller(plan, plan['episodes'][0])
    first = controller.decide(0)['configuration']
    for sequence in (1,2):
        controller.observe({'configuration':first, 'sizeBin':'small', 'status':'error',
            'durationMs':10, 'tokens':{'value':10,'knownPartial':None},
            'failures':['step-limit'], 'sequenceIndex':sequence})
    assert controller.decide(2)['configuration'] != first
    assert controller.decide(3)['configuration'] != first
    assert controller.decide(4)['configuration'] == first


def test_failure_classification_keeps_operation_distinct():
    from ctxbench.adaptive.study_runner import classify_failures
    from ctxbench.benchmark.models import TrialTrace
    class Result:
        trace = TrialTrace(toolCalls=[{'isError':True}])
        status = 'success'
        errorMessage = None
        strategy = 'local_mcp'
    assert classify_failures(Result()) == ['operation']
    Result.status = 'error'
    Result.errorMessage = 'Local MCP strategy exceeded max_steps=8.'
    assert classify_failures(Result()) == ['operation','step-limit']
    Result.trace = TrialTrace()
    Result.errorMessage = 'Connection lost'
    assert classify_failures(Result(), ConnectionError()) == ['transport']
    assert classify_failures(Result(), RuntimeError()) == ['unknown']


def test_structured_failure_evidence_from_engine_trace():
    from ctxbench.adaptive.study_runner import classify_failures
    from ctxbench.benchmark.models import TrialTrace
    class Result:
        status = 'error'
        errorMessage = 'request failed'
        strategy = 'local_mcp'
        trace = TrialTrace(aiTrace={'events':[{'type':'error','metadata':{
            'exceptionModule':'mcp.shared.exceptions','exceptionType':'McpError'}}]})
    assert classify_failures(Result()) == ['transport']
    Result.trace = TrialTrace(aiTrace={'events':[{'type':'error','metadata':{
        'exceptionModule':'openai','exceptionType':'APIStatusError'}}]})
    assert classify_failures(Result()) == ['provider']
    Result.trace = TrialTrace(aiTrace={'events':[{'type':'error','metadata':{
        'exceptionModule':'builtins','exceptionType':'KeyError'}}]})
    assert classify_failures(Result()) == ['tool-use']


def test_tool_delay_records_each_call(frozen, tmp_path):
    definition = make_study(tmp_path, frozen,
        policies={'mcp': {'type':'fixed','configuration':'local-mcp-repoqa-ops'}}, comparisons=[],
        scenarios={'tool-delay': [{'configuration':'local-mcp-repoqa-ops','scope':'tool-call',
                                   'delayMs':100,'firstRequest':1,'lastRequest':1}]})
    path = Path(study.prepare(definition=definition, output=tmp_path/'study-tool-delay')['prepared'])
    class Clock:
        time = 0
        def now(self): return self.time
        def sleep(self, seconds): self.time += seconds
    clock = Clock()
    class Runtime:
        calls = 0
        def call_tool(self, name, args): self.calls += 1
    runtime = Runtime()
    def execute(trial, engine, **kwargs):
        if 'local_mcp_runtime_decorator' in kwargs:
            decorated = kwargs['local_mcp_runtime_decorator'](runtime)
            decorated.call_tool('x', {})
            decorated.call_tool('x', {})
        return mock_execute(trial, engine)
    from ctxbench.adaptive.study_runner import run
    plan = sealed_read(path)
    packet = run(plan, plan['episodes'][0], path.parent/'episodes'/plan['episodes'][0]['id'],
                 monotonic=clock.now, sleeper=clock.sleep, execution=execute)[0]
    assert packet['decision']['toolCallsDelayed'] == 2
    assert packet['decision']['toolDelayRequestedMs'] == 200
    assert round(packet['decision']['toolDelayActualMs']) == 200
    assert round(packet['observation']['durationMs']) == 200


def test_budget_overshoot_stops_remaining_requests(frozen, tmp_path):
    definition = make_study(tmp_path, frozen, policies={
        'budget':{'type':'budget','probeInterval':100},
        'inline':{'type':'fixed','configuration':'inline-code-full'},
        'mcp':{'type':'fixed','configuration':'local-mcp-repoqa-ops'}},
        latencyLimitMs=None, tokenBudget=700, comparisons=[])
    path = Path(study.prepare(definition=definition, output=tmp_path/'budget-overshoot')['prepared'])
    from ctxbench.adaptive.study_runner import run
    plan = sealed_read(path)
    def expensive(trial, engine, **kwargs):
        result = mock_execute(trial, engine)
        return result.model_copy(update={'usage': {'totalTokens': 1000}})
    packets = run(plan, plan['episodes'][0], path.parent/'episodes'/plan['episodes'][0]['id'], execution=expensive)
    assert packets[0]['ledger']['overshoot'] == 300
    assert all(p['result'] is None for p in packets[1:])
