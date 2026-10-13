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
