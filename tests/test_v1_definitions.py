import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from ctxbench.benchmark.definitions import definition_schema, planner_payload, resolve_definition
from ctxbench.benchmark.experiment_loader import load_experiment
from ctxbench.benchmark.models import DatasetProvenance
from ctxbench.benchmark.runspec_generator import generate_runspecs
from ctxbench.dataset.provider import DatasetProvider


def definition():
    return {
        'schemaVersion': 3, 'kind': 'benchmark', 'id': 'v1',
        'dataset': {'root': str(Path('tests/fixtures/fake_dataset/dataset').resolve())},
        'models': {'one': {'provider': 'mock', 'name': 'mock', 'modelParams': {'temperature': 0.2}},
                   'two': {'provider': 'mock', 'name': 'mock-two'}},
        'configurations': {name: {'strategy': 'inline', 'representation': 'json', 'surface': 'full'}
                           for name in ['a', 'b']},
        'surfaces': {'full': {'type': 'full_context'}},
        'candidates': [['one', 'a'], ['two', 'b']],
        'modelParams': {'max_tokens': 42}, 'taskParams': {'extra': 'task-only'},
        'execution': {'repeats': 2, 'options': {'max_steps': 3}},
        'evaluation': {'judges': ['one']},
    }


def test_candidates_and_parameter_ownership(tmp_path):
    path = tmp_path / 'experiment.json'
    path.write_text(json.dumps(definition()))
    exp = load_experiment(path)
    adapter = DatasetProvider.from_dataset(exp.dataset)
    trials = generate_runspecs(exp, tmp_path, adapter, DatasetProvenance(id='fake', version='1'))
    assert len(trials) == 4
    assert {(t.modelId, t.configurationId) for t in trials} == {('one', 'a'), ('two', 'b')}
    assert all(t.parameters['extra'] == 'task-only' and 'extra' not in t.params for t in trials)
    assert all(t.params['max_tokens'] == 42 and t.params['max_steps'] == 3 for t in trials)
    assert all('Avery Example' in t.taskStatement for t in trials)
    assert trials[0].params['temperature'] == 0.2
    assert exp.evaluation.judges[0].params['temperature'] == 0.2


def test_inheritance_preserves_declaring_input_path_and_replaces_arrays(tmp_path):
    base = tmp_path / 'base'
    child = tmp_path / 'child'
    base.mkdir(); child.mkdir()
    data = definition()
    data['dataset'] = {'root': 'dataset'}
    (base / 'base.json').write_text(json.dumps(data))
    target = child / 'child.json'
    target.write_text(json.dumps({'extends': '../base/base.json', 'modelParams': {'temperature': 0},
                                 'candidates': [['one', 'b']], 'taskParams': {'extra': None}}))
    resolved = resolve_definition(target)
    assert resolved['dataset']['root'] == str(base / 'dataset')
    assert resolved['modelParams'] == {'max_tokens': 42, 'temperature': 0}
    assert resolved['candidates'] == [['one', 'b']]
    assert resolved['taskParams'] == {}
    assert 'extends' not in resolved
    assert load_experiment(target).selectedCandidates == [('one', 'b')]


def test_inheritance_cycle_fails(tmp_path):
    path = tmp_path / 'cycle.json'
    path.write_text('{"extends":"cycle.json"}')
    with pytest.raises(ValueError, match='cycle'):
        resolve_definition(path)


@pytest.mark.parametrize('change', ['unknown', 'duplicate', 'params', 'parameters', 'version', 'empty', 'extra-model'])
def test_invalid_definitions_fail(change):
    data = definition()
    if change == 'unknown': data['candidates'][0][1] = 'missing'
    if change == 'duplicate': data['candidates'] *= 2
    if change == 'params': data['params'] = {}
    if change == 'parameters': data['parameters'] = {}
    if change == 'version': data['schemaVersion'] = 2
    if change == 'empty': data['candidates'] = []
    if change == 'extra-model': data['models']['one']['params'] = {}
    with pytest.raises((ValueError, ValidationError)):
        planner_payload(data)


def test_published_schema_matches_installed_schema():
    assert json.loads(Path('schemas/experiment-v1.schema.json').read_text()) == definition_schema()


def test_cascade_policy_accepts_one_fallback_and_rejects_more():
    data = definition()
    data['kind'] = 'adaptive'
    data['adaptation'] = {
        'policy': {'type': 'cascade', 'candidate': ['one', 'a'],
                   'fallbacks': [['two', 'b']], 'minimumResponseLength': 4},
        'workload': [{'taskId': 'task_role', 'instanceId': 'person-001'}],
    }
    assert planner_payload(data)['experimentKind'] == 'adaptive'
    data['adaptation']['policy']['fallbacks'].append(['one', 'b'])
    with pytest.raises(ValidationError):
        planner_payload(data)


def test_legacy_kind_adaptive_definition_cannot_create_a_v1_plan(tmp_path):
    from ctxbench.commands.plan import plan_command

    data = definition()
    data["kind"] = "adaptive"
    data["adaptation"] = {
        "policy": {"type": "static", "candidate": ["one", "a"]},
        "workload": [{"taskId": "task_role", "instanceId": "person-001"}],
    }
    source = tmp_path / "old-adaptive-definition.json"
    source.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Legacy kind=adaptive definitions"):
        plan_command(str(source), str(tmp_path / "output"))


@pytest.mark.parametrize('policy', [
    {'type': 'utility', 'latencyWeight': 1, 'tokenWeight': 1},
    {'type': 'budget', 'tokenBudget': 100, 'bestEffort': True},
    {'type': 'explore', 'seed': 7, 'explorationProbability': 0.2,
     'latencyWeight': 1, 'tokenWeight': 1},
    {'type': 'circuit_breaker', 'candidate': ['one', 'a'], 'fallbacks': [['two', 'b']]},
])
def test_s10_controller_shapes_are_in_definition_schema(policy):
    data = definition()
    data['kind'] = 'adaptive'
    data['adaptation'] = {'policy': policy,
                          'tokenQuota': {'tokens': 1000, 'windowSeconds': 60},
                          'workload': [{'taskId': 'task_role', 'instanceId': 'person-001'}],
                          'phases': [{'name': 'fault', 'firstRequest': 1, 'lastRequest': 1,
                                      'toolFailureRate': 0.1, 'failureSeed': 4}]}
    assert planner_payload(data)['experimentKind'] == 'adaptive'
