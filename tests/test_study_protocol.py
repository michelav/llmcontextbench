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


def test_path_map_relocates_recorded_paths_read_only(frozen, tmp_path, monkeypatch):
    path = Path(study.prepare(definition=make_study(tmp_path, frozen), output=tmp_path/'study-moved')['prepared'])
    sealed = path.read_bytes()
    moved = tmp_path/'elsewhere'
    moved.mkdir()
    (tmp_path/'baseline').rename(moved/'baseline')
    (tmp_path/'experiment.json').rename(moved/'experiment.json')
    with pytest.raises(FileNotFoundError):
        study.status(path)
    path_map = [f'{tmp_path}={moved}']
    assert 'sourceDrift' not in study.status(path, path_map=path_map)
    assert 'sourceDrift' not in study.analyze(path, bootstrap_replicates=10, path_map=path_map)
    assert path.read_bytes() == sealed
    original = baseline.measurement_sources()
    drifted = {**original, 'files': {**original['files'], 'src/ctxbench/adaptive/study_runner.py': 'changed'}}
    monkeypatch.setattr(baseline, 'measurement_sources', lambda: drifted)
    with pytest.raises(ValueError, match='measurement source fingerprint mismatch'):
        study.status(path, path_map=path_map)
    assert study.status(path, path_map=path_map, allow_source_drift=True)['sourceDrift'] == \
        ['src/ctxbench/adaptive/study_runner.py']


def test_path_map_entries_and_longest_prefix():
    pairs = study.parse_path_map(['/old=/new', '/old/baselines=/data/baselines'])
    assert study.local_path('/old/baselines/v3/frozen.json', pairs) == Path('/data/baselines/v3/frozen.json')
    assert study.local_path('/old/experiment.json', pairs) == Path('/new/experiment.json')
    assert study.local_path('/older/x', pairs) == Path('/older/x')
    for bad in ('relative=/new', '/old', '/old='):
        with pytest.raises(ValueError, match='OLD=NEW'):
            study.parse_path_map([bad])


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


def _reliability_controller(frozen, tmp_path, **options):
    definition = make_study(tmp_path, frozen, policies={'r': {'type':'reliability',
        'failureClasses':['step-limit'], 'window':3, 'minimumObservations':2,
        'failureRateThreshold':0.5, 'cooldownRequests':2, 'probeInterval':100, **options}}, comparisons=[])
    path = Path(study.prepare(definition=definition, output=tmp_path/f'study-rel-{len(options)}')['prepared'])
    plan = sealed_read(path)
    return Controller(plan, plan['episodes'][0])


def _observe(controller, cid, sequence, *, failures=(), tokens=10, partial=None, size='small'):
    controller.observe({'configuration':cid, 'sizeBin':size, 'status':'error' if failures else 'success',
        'durationMs':10, 'tokens':{'value':tokens,'knownPartial':partial},
        'failures':list(failures), 'sequenceIndex':sequence})


@pytest.mark.parametrize('reset', [False, True])
def test_reliability_recovery_probe_closes_circuit_only_with_reset(frozen, tmp_path, reset):
    controller = _reliability_controller(frozen, tmp_path, **({'resetOnRecovery': True} if reset else {}))
    first = controller.decide(0)['configuration']
    for sequence in (1, 2):
        _observe(controller, first, sequence, failures=['step-limit'])
    assert controller.decide(2)['configuration'] != first
    probe = controller.decide(4)
    assert (probe['configuration'], probe['reason']) == (first, 'recovery_probe')
    _observe(controller, first, 5)
    controller.decide(5)
    # v1 behaviour re-excludes immediately because old failures stay in the window.
    assert (first in controller.excluded_until) is (not reset)
    if reset:
        _observe(controller, first, 6, failures=['step-limit'])
        controller.decide(6)
        assert first in controller.excluded_until


def _budget_controller(frozen, tmp_path, name, **options):
    definition = make_study(tmp_path, frozen, policies={'budget':{'type':'budget','probeInterval':100, **options},
                                      'inline':{'type':'fixed','configuration':'inline-code-full'},
                                      'mcp':{'type':'fixed','configuration':'local-mcp-repoqa-ops'}},
                            latencyLimitMs=None, tokenBudget=700, comparisons=[])
    plan = sealed_read(Path(study.prepare(definition=definition, output=tmp_path/name)['prepared']))
    return plan, Controller(plan, plan['episodes'][0])


def test_budget_bounded_unknown_usage_keeps_serving(frozen, tmp_path):
    plan, controller = _budget_controller(frozen, tmp_path, 'budget-bounded', unknownUsage='bounded')
    cid = controller.decide(0)['configuration']
    assert cid is not None
    _observe(controller, cid, 1, tokens=None, partial=5)
    assert controller.decide(1)['configuration'] is not None
    ledger = controller.ledger()
    bound = plan['tokenQuantiles'][cid]['small']['p95']
    assert ledger['knownTokens'] == 5 and ledger['unknownConsumption'] is True
    assert ledger['estimatedTokens'] == max(0, bound-5)
    assert ledger['estimatedTokensProvenance'] == 'estimated'


def test_budget_expected_forecast_does_not_read_future_requests(frozen, tmp_path):
    plan, controller = _budget_controller(frozen, tmp_path, 'budget-expected', forecast='expected')
    workload = controller.episode['workload']
    controller.episode = {**controller.episode, 'workload': workload[:1] + ['unknown-future']*(len(workload)-1)}
    assert controller.decide(0)['configuration'] is not None
    assert abs(sum(plan['calibrationSizeMix'].values()) - 1) < 1e-9


@pytest.mark.parametrize('scope', ['global', 'bin'])
def test_router_incumbent_scope(frozen, tmp_path, scope):
    definition = make_study(tmp_path, frozen, policies={'router': {'type':'router','adaptive':False,
        'probeInterval':100, 'incumbentScope':scope}}, comparisons=[])
    plan = sealed_read(Path(study.prepare(definition=definition, output=tmp_path/f'scope-{scope}')['prepared']))
    inline, mcp = plan['configurations']
    for cid, size, tokens in ((inline,'small',1), (mcp,'small',100), (inline,'large',100), (mcp,'large',1)):
        plan['estimates'][cid][size].update(latencyMs=10, tokens=tokens)
    controller = Controller(plan, plan['episodes'][0])
    preferred = {'small': inline, 'large': mcp}
    matches = []
    for index, instance in enumerate(plan['episodes'][0]['workload'][:8]):
        size = plan['requests'][instance]['sizeBin']
        matches.append(controller.decide(index)['configuration'] == preferred[size])
    assert all(matches) is (scope == 'bin')


def test_episode_ids_cover_study_settings(frozen, tmp_path):
    ids = []
    for limit in (1000, 1000, 2000):
        path = study.prepare(definition=make_study(tmp_path, frozen, latencyLimitMs=limit),
                             output=tmp_path/f'ids-{len(ids)}')['prepared']
        ids.append([e['id'] for e in sealed_read(Path(path))['episodes']])
    assert ids[0] == ids[1]
    assert not set(ids[0]) & set(ids[2])


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


@pytest.mark.parametrize('name', ['study', 'baseline'])
def test_checked_in_schemas_match_models(name):
    from ctxbench.studies.models import Baseline
    model = {'study': Study, 'baseline': Baseline}[name]
    expected = json.dumps(model.model_json_schema(), indent=2) + '\n'
    assert Path(f'schemas/studies/{name}.schema.json').read_text() == expected


def _router(frozen, tmp_path, name, *, limit=1000, **options):
    definition = make_study(tmp_path, frozen, latencyLimitMs=limit, comparisons=[],
        policies={'router': {'type':'router','adaptive':True,'probeInterval':100, **options}})
    plan = sealed_read(Path(study.prepare(definition=definition, output=tmp_path/name)['prepared']))
    inline, mcp = plan['configurations']
    for cid in plan['configurations']:
        for size in ('small', 'large'):
            plan['estimates'][cid][size].update(latencyMs=100, tokens=100 if cid == inline else 10)
            plan['latencyQuantiles'][cid][size] = {'0.5': 100, '0.75': 120, '0.9': 150, '0.95': 200}
    return plan, inline, mcp


def test_pooled_ratio_detects_slowdown_across_bins(frozen, tmp_path):
    for estimator, detected in (('per-bin-mean', False), ('pooled-ratio', True)):
        plan, inline, mcp = _router(frozen, tmp_path, f'pooled-{estimator}', estimator=estimator)
        controller = Controller(plan, plan['episodes'][0])
        for sequence, size in enumerate(('small', 'large', 'small'), 1):
            controller.index = sequence
            controller.observe({'configuration':mcp, 'sizeBin':size, 'status':'success', 'durationMs':200,
                                'tokens':{'value':10,'knownPartial':None}, 'failures':[], 'sequenceIndex':sequence})
        assert (controller._estimate(mcp, 'large', 'durationMs') == 200) is detected


def test_estimate_ttl_restores_calibration(frozen, tmp_path):
    plan, inline, mcp = _router(frozen, tmp_path, 'ttl', estimator='pooled-ratio', estimateTtlRequests=5)
    controller = Controller(plan, plan['episodes'][0])
    for sequence in (1, 2, 3):
        _observe(controller, mcp, sequence)
        controller.observed[(mcp, 'all')][-1]['durationMs'] = 300
    controller.index = 3
    assert controller._estimate(mcp, 'small', 'durationMs') == 300
    controller.index = 9
    assert controller._estimate(mcp, 'small', 'durationMs') == 100


def test_quantile_routing_excludes_heavy_tail(frozen, tmp_path):
    plan, inline, mcp = _router(frozen, tmp_path, 'quantile', limit=130, latencyQuantile=0.9)
    controller = Controller(plan, plan['episodes'][0])
    # Both means (100 ms) meet the limit, but no p90 (150 ms) does; the faster tail wins on latency.
    plan['latencyQuantiles'][inline]['small']['0.9'] = 140
    plan['latencyQuantiles'][inline]['large']['0.9'] = 140
    assert controller.decide(0)['configuration'] == inline
    mean_plan, inline, mcp = _router(frozen, tmp_path, 'mean', limit=130)
    assert Controller(mean_plan, mean_plan['episodes'][0]).decide(0)['configuration'] == mcp


@pytest.mark.parametrize('enabled', [False, True])
def test_objective_miss_outranks_token_cost(frozen, tmp_path, enabled):
    plan, inline, mcp = _router(frozen, tmp_path, f'miss-{enabled}', switchOnObjectiveMiss=enabled,
                                cooldownRequests=0, estimator='pooled-ratio')
    controller = Controller(plan, plan['episodes'][0])
    assert controller.decide(0)['configuration'] == mcp
    for sequence in (1, 2, 3):
        _observe(controller, mcp, sequence)
        controller.observed[(mcp, 'all')][-1]['durationMs'] = 5000
    assert controller.decide(3)['configuration'] == (inline if enabled else mcp)


def test_targeted_probe_returns_to_abandoned_configuration(frozen, tmp_path):
    plan, inline, mcp = _router(frozen, tmp_path, 'targeted', switchOnObjectiveMiss=True, cooldownRequests=0,
                                estimator='pooled-ratio', probeMode='targeted', avoidedProbeInterval=3)
    controller = Controller(plan, plan['episodes'][0])
    controller.decide(0)
    for sequence in (1, 2, 3):
        _observe(controller, mcp, sequence)
        controller.observed[(mcp, 'all')][-1]['durationMs'] = 5000
    assert controller.decide(3)['configuration'] == inline
    assert mcp in controller.avoided
    decisions = [controller.decide(index) for index in range(4, 8)]
    assert [d['probe'] for d in decisions] == [False, False, True, False]
    assert decisions[2]['configuration'] == mcp and decisions[2]['reason'] == 'scheduled_probe'


def test_router_probe_options_are_validated(frozen):
    base = {'baseline':str(frozen), 'seeds':[1], 'repeats':1, 'latencyLimitMs':1, 'scenarios':{'s':[]}}
    with pytest.raises(ValueError, match='avoidedProbeInterval'):
        Study.model_validate({**base, 'policies':{'r':{'type':'router','adaptive':True,'probeMode':'targeted'}}})
    with pytest.raises(ValueError, match='minimumObservations'):
        Study.model_validate({**base, 'policies':{'r':{'type':'router','adaptive':True,'minimumObservations':6}}})


def test_target_subset_builds_short_balanced_pilots(frozen, tmp_path):
    held_out = sealed_read(frozen)['plan']['split']['heldOut']
    full = sealed_read(Path(study.prepare(definition=make_study(tmp_path, frozen), output=tmp_path/'full')['prepared']))
    subset = held_out[:4]
    pilot = sealed_read(Path(study.prepare(definition=make_study(tmp_path, frozen, targets=subset),
                                           output=tmp_path/'pilot')['prepared']))
    workload = pilot['episodes'][0]['workload']
    sizes = [pilot['requests'][instance]['variant'] for instance in workload]
    assert len(workload) == len(full['episodes'][0]['workload']) * 4 // len(held_out)
    assert {pilot['requests'][instance]['target'] for instance in workload} == set(subset)
    assert len(set(sizes.count(size) for size in set(sizes))) == 1
    assert not {e['id'] for e in pilot['episodes']} & {e['id'] for e in full['episodes']}
    calibration = sealed_read(frozen)['plan']['split']['calibration'][0]
    with pytest.raises(ValueError, match='held-out targets'):
        study.prepare(definition=make_study(tmp_path, frozen, targets=[calibration]), output=tmp_path/'bad-targets')


def _burst_study(tmp_path, frozen, **overrides):
    base = Path(study.prepare(definition=make_study(tmp_path, frozen, comparisons=[]), output=tmp_path/f'probe-size-{len(list(tmp_path.glob("probe-size-*")))}')['prepared'])
    plan = sealed_read(base)
    bins = [plan['requests'][i]['sizeBin'] for i in plan['episodes'][0]['workload']]
    small, large, total = bins.count('small'), bins.count('large'), len(bins)
    order = {'phases': [{'lastRequest': small//2, 'sizes': ['small']},
                        {'lastRequest': small//2+large, 'sizes': ['large'], 'disturbance': True},
                        {'lastRequest': total, 'sizes': ['small']}]}
    definition = dict(
        policies={'inline': {'type': 'fixed', 'configuration': 'inline-code-full'},
                  'mcp': {'type': 'fixed', 'configuration': 'local-mcp-repoqa-ops'},
                  'blind': {'type': 'blind-router', 'adaptive': True, 'probeTriggers': ['periodic'], 'probeInterval': 5}},
        scenarios={'stationary': [], 'burst': []}, workloads={'burst': order},
        tokenRateBudget={'perRequest': 10, 'window': 4},
        derivedArms={'oracle': {'type': 'phase-oracle', 'normal': 'inline-code-full', 'disturbance': 'local-mcp-repoqa-ops'},
                     'budget-oracle': {'type': 'budget-oracle'},
                     'size-aware': {'type': 'schedule', 'default': {'small': 'inline-code-full', 'large': 'local-mcp-repoqa-ops'}}},
        comparisons=[['blind', 'oracle']])
    definition.update(overrides)
    return make_study(tmp_path, frozen, **definition), (small, large, total)


def test_workload_order_reorders_the_same_requests_per_scenario(frozen, tmp_path):
    definition, (small, large, total) = _burst_study(tmp_path, frozen)
    plan = sealed_read(Path(study.prepare(definition=definition, output=tmp_path/'burst')['prepared']))
    by = {(e['policyName'], e['scenarioName']): e for e in plan['episodes']}
    stationary, burst = by[('inline', 'stationary')]['workload'], by[('inline', 'burst')]['workload']
    assert sorted(stationary) == sorted(burst) and stationary != burst
    assert by[('mcp', 'burst')]['workload'] == burst
    bins = [plan['requests'][i]['sizeBin'] for i in burst]
    assert bins[small//2:small//2+large] == ['large']*large and 'large' not in bins[:small//2]
    assert [p.get('disturbance') for p in plan['phases']['burst']] == [False, True, False]
    assert 'disturbance' not in plan['phases']['stationary'][0]


def test_workload_order_must_use_every_request_once(frozen, tmp_path):
    _, (small, large, total) = _burst_study(tmp_path, frozen)
    definition, _ = _burst_study(tmp_path, frozen,
        workloads={'burst': {'phases': [{'lastRequest': total, 'sizes': ['large']}]}})
    with pytest.raises(ValueError, match='runs out'):
        study.prepare(definition=definition, output=tmp_path/'bad-order')
    definition, _ = _burst_study(tmp_path, frozen,
        workloads={'burst': {'phases': [{'lastRequest': total-1, 'sizes': ['small', 'large']}]}})
    with pytest.raises(ValueError, match='cover the whole workload'):
        study.prepare(definition=definition, output=tmp_path/'short-order')
    with pytest.raises(ValueError, match='defined scenarios'):
        Study.model_validate({'baseline': 'b', 'seeds': [1], 'repeats': 1, 'scenarios': {'s': []},
                              'policies': {'f': {'type': 'fixed', 'configuration': 'x'}},
                              'workloads': {'missing': {'phases': [{'lastRequest': 1, 'sizes': ['small']}]}}})



def test_scenario_seeds_restrict_runs_and_pair_within_the_subset(frozen, tmp_path):
    definition, (small, large, total) = _burst_study(tmp_path, frozen, seeds=[201, 202],
                                                     scenarioSeeds={'burst': [202]}, comparisons=[['inline', 'mcp']])
    path = Path(study.prepare(definition=definition, output=tmp_path/'placed')['prepared'])
    plan = sealed_read(path)
    runs = {(e['scenarioName'], e['seed']) for e in plan['episodes']}
    assert runs == {('stationary', 201), ('stationary', 202), ('burst', 202)}
    unrestricted, _ = _burst_study(tmp_path, frozen, seeds=[201, 202], comparisons=[['inline', 'mcp']])
    full = sealed_read(Path(study.prepare(definition=unrestricted, output=tmp_path/'unplaced')['prepared']))
    ids = {(e['policyName'], e['scenarioName'], e['seed']): e['id'] for e in full['episodes']}
    assert all(ids[(e['policyName'], e['scenarioName'], e['seed'])] == e['id'] for e in plan['episodes'])
    for policy in ('inline', 'mcp'):
        study.episode(prepared=path, policy=policy, scenario='burst', seed=202, repeat=1, execution=mock_execute)
    burst = next(c for c in study.analyze(path, bootstrap_replicates=20)['comparisons'] if c['scenario'] == 'burst')
    assert burst['incomplete'] is False and burst['pairedRequests'] == total
    for bad in ({'missing': [201]}, {'burst': [999]}, {'burst': []}, {'burst': [201, 201]}):
        with pytest.raises(ValueError, match='scenario seeds'):
            Study.model_validate({'baseline': 'b', 'seeds': [201], 'repeats': 1, 'scenarios': {'burst': []},
                                  'policies': {'f': {'type': 'fixed', 'configuration': 'x'}}, 'scenarioSeeds': bad})

def test_derived_arms_need_fixed_arms_and_a_budget(frozen, tmp_path):
    definition, _ = _burst_study(tmp_path, frozen, policies={
        'inline': {'type': 'fixed', 'configuration': 'inline-code-full'},
        'blind': {'type': 'blind-router', 'adaptive': True}})
    with pytest.raises(ValueError, match='requires fixed policies'):
        study.prepare(definition=definition, output=tmp_path/'no-fixed')
    with pytest.raises(ValueError, match='requires tokenRateBudget'):
        Study.model_validate({'baseline': 'b', 'seeds': [1], 'repeats': 1, 'scenarios': {'s': []},
                              'policies': {'f': {'type': 'fixed', 'configuration': 'x'}},
                              'derivedArms': {'o': {'type': 'budget-oracle'}}})


def test_analysis_reports_excess_lags_and_derived_arms(frozen, tmp_path):
    definition, (small, large, total) = _burst_study(tmp_path, frozen)
    path = Path(study.prepare(definition=definition, output=tmp_path/'burst-run')['prepared'])
    for policy in ('inline', 'mcp', 'blind'):
        study.episode(prepared=path, policy=policy, scenario='burst', seed=201, repeat=1, execution=mock_execute)
    report = study.analyze(path, bootstrap_replicates=50)
    rows = {(r['policyName'], r['scenarioName']): r for r in report['summaries']}
    for name in ('oracle', 'budget-oracle', 'size-aware'):
        derived = rows[(name, 'burst')]
        assert derived['derived'] is True and derived['provenance'] == 'derived' and derived['completed'] == total
        assert rows[(name, 'stationary')]['completed'] == 0
    assert rows[('inline', 'burst')]['budgetExcess'] is not None
    assert [p['budgetExcess'] is not None for p in rows[('inline', 'burst')]['phaseSummaries']] == [True]*3
    assert rows[('budget-oracle', 'burst')]['budgetExcess'] <= min(rows[(n, 'burst')]['budgetExcess'] for n in ('inline', 'mcp'))
    burst_comparison = next(c for c in report['comparisons'] if c['scenario'] == 'burst')
    assert burst_comparison['pairedRequests'] == total



def _blind_utility(frozen, tmp_path, name, weight, *, adaptive=True, **options):
    policy = {'type':'blind-router','adaptive':adaptive,'estimateWindow':3,'minimumObservations':2, **options}
    definition = make_study(tmp_path, frozen, latencyLimitMs=None, latencyCostTokensPerSecond=weight, comparisons=[],
                            policies={'blind': policy})
    plan = sealed_read(Path(study.prepare(definition=definition, output=tmp_path/name)['prepared']))
    inline, mcp = plan['configurations']
    # Inline: more tokens, faster; remote MCP: fewer tokens, slower. Break-even lambda = 900 tokens / 1 s = 900.
    for size in plan['estimates'][inline]:
        plan['estimates'][inline][size].update(latencyMs=1000, tokens=1000)
        plan['estimates'][mcp][size].update(latencyMs=2000, tokens=100)
    return plan, inline, mcp


def _served(controller, cid, sequence, *, latency, tokens, size='small'):
    controller.index = sequence
    controller.observe({'configuration':cid, 'sizeBin':size, 'status':'success', 'durationMs':latency,
                        'tokens':{'value':tokens,'knownPartial':None}, 'failures':[], 'sequenceIndex':sequence})


@pytest.mark.parametrize('weight, expected', [(500, 'mcp'), (2000, 'inline')])
def test_blind_utility_starts_on_the_lower_pooled_cost(frozen, tmp_path, weight, expected):
    plan, inline, mcp = _blind_utility(frozen, tmp_path, f'blind-utility-{weight}', weight)
    assert Controller(plan, plan['episodes'][0]).decide(0)['configuration'] == {'mcp': mcp, 'inline': inline}[expected]


def test_blind_utility_never_reads_request_features(frozen, tmp_path):
    plan, inline, mcp = _blind_utility(frozen, tmp_path, 'blind-features', 500)
    sizes = {plan['requests'][i]['sizeBin'] for i in plan['episodes'][0]['workload']}
    assert len(sizes) > 1
    # Calibration that differs per size bin must not matter: the router only sees pooled values.
    controller = Controller(plan, plan['episodes'][0])
    choices = [controller.decide(i)['configuration'] for i in range(len(plan['episodes'][0]['workload']))]
    assert set(choices) == {mcp}
    plan['estimates'][inline]['small'].update(tokens=10)
    pooled = Controller(plan, plan['episodes'][0])._blind_cost(inline)
    for size in plan['estimates'][inline]:
        plan['estimates'][inline][size]['tokens'] = 10 if size == 'small' else 1000
    assert Controller(plan, plan['episodes'][0])._blind_cost(inline) == pooled


def test_blind_utility_hysteresis_switches_only_on_a_material_gain(frozen, tmp_path):
    # J(inline) = 1000 + 0.5*1000 = 1500 (calibration); J(mcp) observed = 100 + 0.5*latency:
    # 1550 at 2900 ms (inline 3 % cheaper), 1700 at 3200 ms (12 % cheaper).
    for latency, threshold, switches in ((2900, 0.05, False), (2900, 0, True), (3200, 0.05, True)):
        plan, inline, mcp = _blind_utility(frozen, tmp_path, f'blind-hysteresis-{latency}-{threshold}', 500,
                                           materialImprovement=threshold)
        controller = Controller(plan, plan['episodes'][0])
        assert controller.decide(0)['configuration'] == mcp
        for sequence in (1, 2):
            _served(controller, mcp, sequence, latency=latency, tokens=100)
        decision = controller.decide(2)
        assert (decision['configuration'] == inline) is switches
        assert decision['reason'] == ('lower_cost' if switches else 'incumbent')


def test_blind_utility_needs_minimum_fresh_observations(frozen, tmp_path):
    plan, inline, mcp = _blind_utility(frozen, tmp_path, 'blind-fresh', 500, materialImprovement=0.05,
                                       estimateTtlRequests=4)
    controller = Controller(plan, plan['episodes'][0])
    controller.decide(0)
    _served(controller, mcp, 1, latency=5000, tokens=100)
    assert controller.decide(1)['configuration'] == mcp        # one observation is below the minimum
    _served(controller, mcp, 2, latency=5000, tokens=100)
    assert controller.decide(2)['configuration'] == inline     # two slow observations: J(mcp) = 2600
    controller.current = mcp
    controller.index = 9
    assert controller._blind_cost(mcp) == pytest.approx(100 + 500*2000/1000)  # expired: back to calibration


def test_blind_utility_probes_the_alternative_either_way_and_frozen_never_probes(frozen, tmp_path):
    plan, inline, mcp = _blind_utility(frozen, tmp_path, 'blind-probe', 500, probeTriggers=['periodic'],
                                       probeInterval=3)
    controller = Controller(plan, plan['episodes'][0])
    decisions = [controller.decide(i) for i in range(7)]
    # The incumbent (mcp) is cheaper and slower: the probe still goes to inline, the faster and dearer one.
    assert [d["probe"] for d in decisions] == [False, False, False, True, False, False, True]
    assert {d['configuration'] for d in decisions if d['probe']} == {inline}
    # The frozen router cannot probe (rejected by the model) and ignores what it observes.
    frozen_plan, _, _ = _blind_utility(frozen, tmp_path, 'blind-frozen', 500, adaptive=False)
    controller = Controller(frozen_plan, frozen_plan['episodes'][0])
    controller.decide(0)
    for sequence in (1, 2, 3):
        _served(controller, mcp, sequence, latency=9000, tokens=100)
    assert [controller.decide(i) for i in range(3, 7)] == [{'configuration': mcp, 'reason': 'incumbent', 'probe': False}]*4


def test_utility_objective_validation_ids_and_reporting(frozen, tmp_path):
    base = {'baseline':str(frozen), 'seeds':[1], 'repeats':1, 'scenarios':{'stationary':[]}}
    with pytest.raises(ValueError, match='on its own'):
        Study.model_validate({**base, 'latencyLimitMs':1000, 'latencyCostTokensPerSecond':500,
                              'policies':{'r':{'type':'blind-router','adaptive':True}}})
    with pytest.raises(ValueError, match='latency-cost objective only'):
        Study.model_validate({**base, 'latencyLimitMs':1000,
                              'policies':{'r':{'type':'blind-router','adaptive':True,'materialImprovement':0.05}}})
    with pytest.raises(ValueError, match='routing requires latencyLimitMs'):
        Study.model_validate({**base, 'latencyCostTokensPerSecond':500,
                              'policies':{'r':{'type':'router','adaptive':True}}})
    blind = {'type':'blind-router','adaptive':True}
    limit = make_study(tmp_path, frozen, policies={'blind': blind}, comparisons=[])
    plan = sealed_read(Path(study.prepare(definition=limit, output=tmp_path/'blind-limit')['prepared']))
    assert 'materialImprovement' in plan['episodes'][0]['policy']
    from ctxbench.studies.study import _policy_identity
    from ctxbench.studies.models import BlindRouterPolicy
    assert set(_policy_identity(BlindRouterPolicy(**blind))) == set(BlindRouterPolicy(**blind).model_dump()) - {
        'materialImprovement', 'minimumObservations', 'estimateTtlRequests'}
    prepared = {}
    for weight in (500, 600):
        definition = make_study(tmp_path, frozen, latencyLimitMs=None, latencyCostTokensPerSecond=weight,
                                policies={'fixed': {'type':'fixed','configuration':'inline-code-full'},
                                          'blind': {**blind, 'materialImprovement':0.05}},
                                comparisons=[['blind', 'fixed']])
        prepared[weight] = Path(study.prepare(definition=definition, output=tmp_path/f'utility-{weight}')['prepared'])
    ids = {weight: {e['id'] for e in sealed_read(path)['episodes']} for weight, path in prepared.items()}
    assert ids[500].isdisjoint(ids[600])
    for e in sealed_read(prepared[500])['episodes']:
        study.episode(prepared=prepared[500], policy=e['policyName'], scenario='stationary', seed=201, repeat=1,
                      execution=mock_execute)
    report = study.analyze(prepared[500])
    for summary in report['summaries']:
        assert summary['meanUtility'] == pytest.approx(summary['tokensLowerBound']/summary['completed']
                                                       + 500*summary['meanLatencyMs']/1000)
    assert 'utility' in report['comparisons'][0]['metrics']
    assert all(arm['meanUtility'] is not None for arm in report['arms'])


@pytest.mark.parametrize('objective', ['limit', 'utility'])
def test_blind_router_reads_nothing_from_the_request(frozen, tmp_path, objective):
    if objective == 'utility':
        plan, inline, mcp = _blind_utility(frozen, tmp_path, 'blind-nothing', 500, probeTriggers=['periodic'],
                                           probeInterval=3, materialImprovement=0.05)
    else:
        definition = make_study(tmp_path, frozen, comparisons=[], policies={'blind': {
            'type':'blind-router','adaptive':True,'probeTriggers':['periodic'],'probeInterval':3}})
        plan = sealed_read(Path(study.prepare(definition=definition, output=tmp_path/'blind-nothing')['prepared']))
        inline, mcp = plan['configurations']
    def run(plan):
        controller, decisions = Controller(plan, plan['episodes'][0]), []
        for i in range(8):
            decisions.append(controller.decide(i))
            controller.observe({'configuration': decisions[-1]['configuration'], 'status': 'success',
                                'durationMs': 1000 + 500*i, 'tokens': {'value': 100 + 50*i, 'knownPartial': None},
                                'failures': [], 'sequenceIndex': i+1})
        return controller, decisions
    _, expected = run(plan)
    # Without any request record (size bin, context fit, executability, target), decisions are unchanged.
    plan['requests'] = {}
    controller, decisions = run(plan)
    assert decisions == expected
    assert {size for _, size in controller.observed} <= {None, 'all'}


def _explicit(frozen, tmp_path, workloads, **overrides):
    (tmp_path / 'workloads.json').write_text(json.dumps(workloads))
    return make_study(tmp_path, frozen, workloadFile=str(tmp_path / 'workloads.json'), **overrides)


def _held_out(frozen):
    plan = sealed_read(frozen)['plan']
    held = set(plan['split']['heldOut'])
    return sorted(i for i, r in plan['requests'].items() if r['target'] in held), plan


def test_explicit_workloads_disturbances_and_scenario_calibration_sizes(frozen, tmp_path):
    held, parent = _held_out(frozen)
    workloads = {'normal': {'201': held[:6], '202': held[6:12]}, 'burst': {'202': held[12:18]}}
    definition = _explicit(frozen, tmp_path, workloads, seeds=[201, 202], scenarios={'normal': [], 'burst': []},
                           scenarioSeeds={'burst': [202]}, disturbances={'burst': {'firstRequest':3, 'lastRequest':4}},
                           calibrationSizes={'burst': ['small']})
    plan = sealed_read(Path(study.prepare(definition=definition, output=tmp_path/'explicit')['prepared']))
    by = {(e['scenarioName'], e['seed'], e['policyName']): e for e in plan['episodes']}
    assert len(by) == 6
    assert by[('normal', 201, 'router')]['workload'] == held[:6]
    assert by[('burst', 202, 'fixed')]['workload'] == held[12:18]
    assert plan['phases']['burst'] == [{'firstRequest':1,'lastRequest':2,'disturbance':False},
                                       {'firstRequest':3,'lastRequest':4,'disturbance':True},
                                       {'firstRequest':5,'lastRequest':6,'disturbance':False}]
    assert plan['phases']['normal'] == [{'firstRequest':1,'lastRequest':6}]
    assert by[('burst', 202, 'router')]['calibrationSizeMix'] == {'small': 1.0}
    assert 'calibrationSizeMix' not in by[('normal', 202, 'router')]
    assert plan['workloadFile']['digest'] == baseline.file_hash(tmp_path / 'workloads.json')
    # A scenario-specific mix is part of the episode identity; without one the identity is unchanged.
    plain = make_study(tmp_path, frozen, workloadFile=str(tmp_path / 'workloads.json'), seeds=[201, 202],
                       scenarios={'normal': [], 'burst': []}, scenarioSeeds={'burst': [202]},
                       disturbances={'burst': {'firstRequest':3, 'lastRequest':4}})
    other = sealed_read(Path(study.prepare(definition=plain, output=tmp_path/'explicit-plain')['prepared']))
    ids = {(e['scenarioName'], e['seed'], e['policyName']): e['id'] for e in other['episodes']}
    assert ids[('normal', 201, 'router')] == by[('normal', 201, 'router')]['id']
    assert ids[('burst', 202, 'router')] != by[('burst', 202, 'router')]['id']


def test_explicit_workloads_are_checked(frozen, tmp_path):
    held, parent = _held_out(frozen)
    calibration = sorted(i for i, r in parent['requests'].items() if r['target'] in parent['split']['calibration'])
    cases = [({'stationary': {'201': held[:4]}, 'extra': {'201': held[:4]}}, {}, 'every scenario'),
             ({'stationary': {'202': held[:4]}}, {}, 'exactly the seeds'),
             ({'stationary': {'201': [held[0], held[0]]}}, {}, 'distinct instances'),
             ({'stationary': {'201': calibration[:3]}}, {}, 'outside the evaluation split'),
             ({'stationary': {'201': held[:4]}, 'other': {'201': held[:5]}},
              {'scenarios': {'stationary': [], 'other': []}}, 'unequal study workloads'),
             ({'stationary': {'201': held[:4]}}, {'calibrationSizes': {'stationary': ['huge']}}, 'size bins'),
             ({'stationary': {'201': held[:4]}}, {'disturbances': {'stationary': {'firstRequest':3, 'lastRequest':5}}},
              'disturbance range exceeds')]
    for n, (workloads, overrides, message) in enumerate(cases):
        definition = _explicit(frozen, tmp_path, workloads, **overrides)
        with pytest.raises(ValueError, match=message):
            study.prepare(definition=definition, output=tmp_path/f'bad-explicit-{n}')
    base = {'baseline': 'b.json', 'seeds': [1], 'repeats': 1, 'scenarios': {'s': []},
            'policies': {'f': {'type': 'fixed', 'configuration': 'c'}}}
    for overrides, message in (({'workloadFile': 'w.json', 'targets': ['t']}, 'excludes'),
                               ({'disturbances': {'x': {'firstRequest':1, 'lastRequest':1}}}, 'name defined scenarios'),
                               ({'calibrationSizes': {'s': []}}, 'nonempty'),
                               ({'workloads': {'s': {'phases': [{'lastRequest':2, 'sizes':['small']}]}},
                                 'disturbances': {'s': {'firstRequest':1, 'lastRequest':1}}}, 'already marks')):
        with pytest.raises(ValueError, match=message):
            Study.model_validate({**base, **overrides})


def test_blind_utility_pools_calibration_over_the_scenario_normal_stream(frozen, tmp_path):
    held, _ = _held_out(frozen)
    plans = []
    for name, sizes in (('all', {}), ('small', {'calibrationSizes': {'stationary': ['small']}})):
        definition = _explicit(frozen, tmp_path, {'stationary': {'201': held[:6]}}, latencyLimitMs=None,
                               latencyCostTokensPerSecond=500, comparisons=[],
                               policies={'blind': {'type':'blind-router','adaptive':False}}, **sizes)
        plan = sealed_read(Path(study.prepare(definition=definition, output=tmp_path/f'pooled-{name}')['prepared']))
        inline, mcp = plan['configurations']
        assert set(plan['estimates'][inline]) == {'small', 'large'}
        # Small: inline J 600 < remote 1100; large: inline 5500 > remote 1100.
        plan['estimates'][inline]['small'].update(latencyMs=1000, tokens=100)
        plan['estimates'][inline]['large'].update(latencyMs=1000, tokens=5000)
        for size in ('small', 'large'):
            plan['estimates'][mcp][size].update(latencyMs=2000, tokens=100)
        plans.append((Controller(plan, plan['episodes'][0]).decide(0)['configuration'], inline, mcp))
    (everything, inline, mcp), (small, _, _) = plans
    assert (everything, small) == (mcp, inline)


def test_burst_workloads_balance_sizes_and_swap_in_contested_instances():
    from ctxbench.adapters.repoqa.burst_workloads import burst_workloads
    selection, evaluation = [], []
    for size in (2048, 8192, 16384, 32768, 65536):
        for n in range(30):
            klass = 'contested' if n < (2 if size == 2048 else 12) else ('isolated' if n % 2 else 'intermediate')
            instance = f'r{n}_ctx{size // 1024}k'
            selection.append({'instance': instance, 'size': size, 'class': klass})
            evaluation.append(instance)
    labels = {e['instance']: e for e in selection}
    size = lambda i: f"{labels[i]['size'] // 1024}k"
    workloads, seeds, disturbances = burst_workloads(selection, evaluation, seeds=[1, 2, 3, 4], length=48,
                                                     burst=16, placements=[13, 17, 21])
    assert seeds == {'S-L-13': [1, 4], 'S-C-13': [1, 4], 'S-D-13': [1, 4], 'S-L-17': [2], 'S-C-17': [2],
                     'S-D-17': [2], 'S-L-21': [3], 'S-C-21': [3], 'S-D-21': [3]}
    assert disturbances['S-L-17'] == {'firstRequest': 17, 'lastRequest': 32}
    stationary = workloads['S-A']['2']
    assert len(stationary) == len(set(stationary)) == 48
    counts = {s: [size(i) for i in stationary].count(s) for s in ('2k', '8k', '16k', '32k', '64k')}
    assert max(counts.values()) - min(counts.values()) <= 1
    large = workloads['S-L-17']['2']
    assert len(set(large)) == 48
    assert {size(i) for i in large[16:32]} == {'32k', '64k'}
    assert {size(i) for i in large[:16] + large[32:]} == {'2k', '8k', '16k'}
    slowdown = workloads['S-D-17']['2']
    assert len(set(slowdown)) == 48 and [size(i) for i in slowdown].count('32k') == 24
    assert {size(i) for i in slowdown} == {'32k', '64k'}
    swapped = workloads['S-C-17']['2']
    assert len(set(swapped)) == 48
    assert [size(i) for i in swapped] == [size(i) for i in stationary]
    assert swapped[:16] == stationary[:16] and swapped[32:] == stationary[32:]
    burst = [labels[i]['class'] for i in swapped[16:32]]
    # Only 2k can run short of contested instances (two exist).
    assert all(c == 'contested' or size(i) == '2k' for c, i in zip(burst, swapped[16:32]))
    again, _, _ = burst_workloads(selection, evaluation, seeds=[1, 2, 3, 4], length=48, burst=16, placements=[13, 17, 21])
    assert again == workloads
    with pytest.raises(ValueError, match='fit the workload'):
        burst_workloads(selection, evaluation, seeds=[1], length=48, burst=16, placements=[40])
