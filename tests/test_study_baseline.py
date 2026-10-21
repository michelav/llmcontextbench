import json
from pathlib import Path

import pytest

from ctxbench.studies import baseline
from ctxbench.studies.models import Baseline
from ctxbench.adaptive.recovery import sealed_read
from ctxbench.adaptive.runner import error_result


@pytest.fixture
def prepared(tmp_path):
    payload = json.loads(Path('tests/fixtures/repoqa_surface_experiment.json').read_text())
    payload['dataset']['root'] = str(Path('datasets/repoqa').resolve())
    payload['scope']['instances'] = []
    payload['execution'] = {'repeats': 1}
    (tmp_path / 'experiment.json').write_text(json.dumps(payload))
    definition = {'experiment': 'experiment.json', 'split': {'seed': 42, 'calibrationTargetsPerLanguage': 1},
                  'seeds': [1, 2], 'repeats': 2, 'contextLimit': 200000, 'outputReservation': 2048}
    (tmp_path / 'baseline.json').write_text(json.dumps(definition))
    return Path(baseline.prepare(definition=tmp_path / 'baseline.json', output=tmp_path / 'baseline')['prepared'])


def execute(trial, engine, **kwargs):
    result = error_result(trial, 'fixture', '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z', 1000)
    return result.model_copy(update={'status': 'success', 'errorMessage': None, 'response': 'code', 'usage': {'totalTokens': 10}})


def test_prepare_matrix_and_target_isolation(prepared):
    plan = sealed_read(prepared)
    assert len(plan['episodes']) == 8
    assert not set(plan['split']['calibration']) & set(plan['split']['heldOut'])
    assert all(len(e['workload']) == 16 for e in plan['episodes'])
    assert all(t['repeatIndex'] == 1 for r in plan['requests'].values() for t in r['trials'].values())
    for seed in [1, 2]:
        orders = [e['workload'] for e in plan['episodes'] if e['seed'] == seed]
        assert all(order == orders[0] for order in orders)
    baseline.verify(plan)


def test_execute_resume_freeze_preserves_all_observations(prepared):
    with pytest.raises(ValueError, match='incomplete'):
        baseline.freeze(prepared=prepared)
    baseline.execute(prepared=prepared, execution=execute)
    def forbidden(*args, **kwargs):
        pytest.fail('completed execution called provider')
    baseline.execute(prepared=prepared, resume=True, execution=forbidden)
    result = baseline.freeze(prepared=prepared)
    frozen = sealed_read(Path(result['frozen']))
    assert len(frozen['observations']) == 128
    assert all(e['usageCoverage'] == e['observations'] for bins in frozen['estimates'].values() for e in bins.values())
    with pytest.raises(ValueError, match='immutable'):
        baseline.freeze(prepared=prepared)


def test_integer_seed_validation():
    data = dict(experiment='experiment.json', split={'seed': 1, 'calibrationTargetsPerLanguage': 1},
                seeds=[True], repeats=1, contextLimit=100, outputReservation=10)
    with pytest.raises(ValueError):
        Baseline(**data)


def test_uncertain_execution_stops_resume(prepared):
    def crash(stage, index):
        if stage == 'execution_finished':
            raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        baseline.execute(prepared=prepared, execution=execute, checkpoint=crash)
    with pytest.raises(ValueError, match='uncertain'):
        baseline.execute(prepared=prepared, execution=execute, resume=True)


def test_explicit_uncertain_retry_records_unknown_usage(prepared):
    from ctxbench.adaptive.study_runner import load_packets
    fired = False
    def crash(stage, index):
        nonlocal fired
        if stage == 'execution_started' and not fired:
            fired = True
            raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        baseline.execute(prepared=prepared, execution=execute, checkpoint=crash)
    baseline.execute(prepared=prepared, execution=execute, resume=True, retry_uncertain=True)
    episode = sealed_read(prepared)['episodes'][0]
    packets = load_packets(prepared.parent / 'episodes' / episode['id'])
    assert packets[0]['uncertainRetries'] == 1
    assert packets[-1]['ledger']['unknownConsumption'] is True


def test_constituent_execution_supports_export_and_metrics(prepared, tmp_path):
    from ctxbench.commands.export import export_command
    from ctxbench.commands.metrics import metrics_command
    from ctxbench.benchmark.provisioning import validate_artifact_directory
    from ctxbench.adaptive.study_runner import run
    plan = sealed_read(prepared)
    episode = plan['episodes'][0]
    root = prepared.parent / 'episodes' / episode['id']
    run(plan, episode, root, execution=execute)
    validate_artifact_directory(root)
    assert export_command(str(root/'evals.jsonl'), output=str(tmp_path/'results.csv')) == 0
    assert (tmp_path/'results.csv').exists()
    assert metrics_command([str(root)], output=str(tmp_path/'metrics')) == 0
    assert (tmp_path/'metrics'/'summary.json').exists()


def test_constituent_execution_supports_standard_eval(prepared):
    from ctxbench.commands.eval import eval_command
    from ctxbench.benchmark.selectors import RunSelector
    from ctxbench.adaptive.study_runner import run
    plan = sealed_read(prepared)
    episode = plan['episodes'][0]
    root = prepared.parent / 'episodes' / episode['id']
    packets = run(plan, episode, root, execution=execute)
    trial_id = packets[0]['result']['trialId']
    assert eval_command(str(root/'responses.jsonl'), selector=RunSelector(trial_id=(trial_id,))) == 0
    evaluations = baseline.rows(root/'evals.jsonl')
    assert len(evaluations) == 1
    assert evaluations[0]['trialId'] == trial_id


def test_policy_only_source_revision_does_not_invalidate_measurements(prepared, monkeypatch):
    plan = sealed_read(prepared)
    current = baseline.measurement_sources()
    monkeypatch.setattr(baseline, 'measurement_sources', lambda: {**current, 'revision':'other-commit'})
    baseline.verify(plan)
    monkeypatch.setattr(baseline, 'measurement_sources', lambda: {**current, 'definitionSchema':'changed'})
    with pytest.raises(ValueError, match='measurement source'):
        baseline.verify(plan)


CALIBRATION = [{'instance': 'py_001_ctx2k', 'weight': 3}, {'instance': 'py_001_ctx16k', 'weight': 1},
               {'instance': 'java_001_ctx8k', 'weight': 1}, {'instance': 'ts_001_ctx2k', 'weight': 1}]
EVALUATION = ['py_002_ctx2k', 'py_002_ctx8k', 'rs_001_ctx16k']


def instance_baseline(tmp_path, calibration=CALIBRATION, evaluation=EVALUATION, strategy=None, **changes):
    payload = json.loads(Path('tests/fixtures/repoqa_surface_experiment.json').read_text())
    payload['dataset']['root'] = str(Path('datasets/repoqa').resolve())
    payload['scope']['instances'] = []
    payload['execution'] = {'repeats': 1}
    if strategy:
        payload['configurations']['local-mcp-repoqa-ops']['strategy'] = strategy
    (tmp_path / 'experiment.json').write_text(json.dumps(payload))
    (tmp_path / 'calibration.json').write_text(json.dumps(calibration))
    (tmp_path / 'evaluation.json').write_text(json.dumps(evaluation))
    definition = {'experiment': 'experiment.json', 'sizeProfile': 'standard',
                  'split': {'calibrationInstances': 'calibration.json', 'evaluationInstances': 'evaluation.json'},
                  'seeds': [1, 2], 'repeats': 1, 'contextLimit': 200000, 'outputReservation': 2048, **changes}
    (tmp_path / 'baseline.json').write_text(json.dumps(definition))
    return lambda: Path(baseline.prepare(definition=tmp_path / 'baseline.json', output=tmp_path / 'baseline')['prepared'])


def test_instance_split_uses_listed_instances_without_balanced_variants(tmp_path):
    plan = sealed_read(instance_baseline(tmp_path)())
    calibration = sorted(e['instance'] for e in CALIBRATION)
    assert plan['split']['calibrationInstances'] == calibration
    assert plan['split']['evaluationInstances'] == sorted(EVALUATION)
    assert plan['split']['calibration'] == ['java_001', 'py_001', 'ts_001']
    assert plan['split']['heldOut'] == ['py_002', 'rs_001']
    assert set(plan['requests']) == set(calibration) | set(EVALUATION)
    assert plan['sizeProfile'] == 'standard' and 'sizeProfile' in plan['definition']
    assert len(plan['episodes']) == 4
    orders = {e['seed']: e['workload'] for e in plan['episodes']}
    assert sorted(orders[1]) == calibration and sorted(orders[2]) == calibration and orders[1] != orders[2]
    baseline.verify(plan)


@pytest.mark.parametrize('calibration,evaluation,message', [
    (CALIBRATION, ['py_001_ctx8k'], 'both sides'),
    (CALIBRATION, ['nope_ctx2k'], 'outside the experiment population'),
    (CALIBRATION[:1] + ['java_001_ctx8k'], EVALUATION, 'weights'),
    (['py_001_ctx2k', 'py_001_ctx2k'], EVALUATION, 'unique'),
])
def test_instance_split_rejects_invalid_lists(tmp_path, calibration, evaluation, message):
    with pytest.raises(ValueError, match=message):
        instance_baseline(tmp_path, calibration, evaluation)()


def test_size_profile_is_declared_with_an_instance_split_only():
    split = {'calibrationInstances': 'c.json', 'evaluationInstances': 'e.json'}
    common = dict(experiment='experiment.json', seeds=[1], repeats=1, contextLimit=100, outputReservation=10)
    with pytest.raises(ValueError, match='sizeProfile'):
        Baseline(split=split, **common)
    with pytest.raises(ValueError, match='sizeProfile'):
        Baseline(split={'seed': 1, 'calibrationTargetsPerLanguage': 1}, sizeProfile='long64', **common)
    assert Baseline(split=split, sizeProfile='long64', **common).sizeProfile == 'long64'


def test_instance_split_rejects_sizes_outside_profile(tmp_path, monkeypatch):
    from ctxbench.studies import baseline as module
    monkeypatch.setitem(module.SIZE_PROFILES, 'standard', frozenset((2048, 4096)))
    with pytest.raises(ValueError, match='outside the standard profile'):
        instance_baseline(tmp_path)()


def test_target_split_keeps_its_definition_shape(prepared):
    plan = sealed_read(prepared)
    assert 'sizeProfile' not in plan['definition']
    assert plan['split']['seed'] == 42 and 'weights' not in plan['split']


def test_remote_mcp_configuration_is_accepted(tmp_path):
    plan = sealed_read(instance_baseline(tmp_path, strategy='remote_mcp')())
    assert plan['manifest']['configurations']['local-mcp-repoqa-ops']['strategy'] == 'remote_mcp'


def test_execute_one_seed_at_a_time_and_weighted_estimates(tmp_path):
    prepared = instance_baseline(tmp_path)()
    tokens = {'py_001_ctx2k': 100, 'py_001_ctx16k': 300, 'java_001_ctx8k': 500, 'ts_001_ctx2k': 900}

    def measured(trial, engine, **kwargs):
        return execute(trial, engine).model_copy(update={'usage': {'totalTokens': tokens[trial.instanceId]}})
    with pytest.raises(ValueError, match='no episode with seed'):
        baseline.execute(prepared=prepared, execution=measured, seed=3)
    assert baseline.execute(prepared=prepared, execution=measured, seed=1) == {'episodes': 2}
    with pytest.raises(ValueError, match='incomplete'):
        baseline.freeze(prepared=prepared)
    baseline.execute(prepared=prepared, execution=measured, seed=2)
    frozen = sealed_read(Path(baseline.freeze(prepared=prepared)['frozen']))
    small = frozen['estimates']['inline-code-full']['small']
    assert small['tokens'] == (3*100 + 900)/4 and small['estimator'] == 'weighted-observations-v1'
    assert frozen['estimates']['inline-code-full']['large']['tokens'] == (300 + 500)/2
    assert all('instanceId' in o for o in frozen['observations'])
