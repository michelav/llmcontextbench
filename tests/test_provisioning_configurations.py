from copy import deepcopy
import json
from pathlib import Path

import pytest

from ctxbench.benchmark.models import Experiment, ProvisioningConfiguration, TrialSpec
from ctxbench.benchmark.runspec_generator import generate_runspecs
from ctxbench.dataset.provider import LocalDatasetPackage
from ctxbench.benchmark.models import DatasetProvenance
from ctxbench.util.artifacts import canonical_trial_identity


def experiment_payload():
    return {
        'id': 'provisioning', 'dataset': {'root': 'tests/fixtures/fake_dataset/dataset'},
        'models': {'m': {'provider': 'mock', 'name': 'mock'}},
        'configurations': {
            'i-json': {'strategy': 'inline', 'representation': 'json'},
            'i-html': {'strategy': 'inline', 'representation': 'html'},
            'f-json': {'strategy': 'local_function', 'representation': 'json'},
        },
        'factors': {'model': ['m'], 'configuration': ['i-json', 'i-html', 'f-json']},
    }


def test_configuration_expansion_and_snapshot(tmp_path):
    payload = experiment_payload()
    exp = Experiment.model_validate(payload)
    from ctxbench.dataset.provider import DatasetProvider
    adapter = DatasetProvider.from_dataset(exp.dataset)
    trials = generate_runspecs(exp, tmp_path, adapter, DatasetProvenance(id='fake', version='1'))
    assert len(trials) == 3
    assert {t.configurationId for t in trials} == set(payload['configurations'])
    snapshot = trials[0].to_persisted_artifact()
    payload['configurations']['i-json']['representation'] = 'html'
    assert TrialSpec.model_validate(snapshot).representation == 'json'
    assert snapshot['metadata']['configurationId'] == snapshot['configurationId']
    snapshot['metadata']['representation'] = 'html'
    with pytest.raises(ValueError, match='Inconsistent'):
        TrialSpec.model_validate(snapshot)


@pytest.mark.parametrize('change', ['legacy', 'duplicate', 'undefined', 'empty', 'unknown', 'extra', 'tool-html', 'uppercase'])
def test_invalid_configuration_contract(change):
    p = experiment_payload()
    if change == 'legacy': p['factors']['strategy'] = ['inline']
    if change == 'duplicate': p['factors']['configuration'] *= 2
    if change == 'undefined': p['factors']['configuration'] = ['missing']
    if change == 'empty': p['factors']['configuration'] = []
    if change == 'unknown': p['configurations']['i-json']['strategy'] = 'mcp'
    if change == 'extra': p['configurations']['i-json']['operationProfile'] = 'future'
    if change == 'tool-html': p['configurations']['f-json']['representation'] = 'html'
    if change == 'uppercase': p['configurations']['Bad'] = p['configurations']['i-json']
    with pytest.raises(ValueError): Experiment.model_validate(p)


def test_identity_encodes_configuration_and_structured_dimensions():
    args = dict(experiment_id='e|x', task_id='t', instance_id='i', provider='mock', model_name='m', strategy='inline', representation='json', repetition=1, configuration_id='a')
    first = canonical_trial_identity(**args)
    assert json.loads(first)['identityVersion'] == 2
    assert first == canonical_trial_identity(**dict(reversed(list(args.items()))))
    assert first != canonical_trial_identity(**{**args, 'configuration_id': 'b'})
    assert first != canonical_trial_identity(**{**args, 'representation': 'html'})
    assert first != canonical_trial_identity(**{**args, 'experiment_id': 'e', 'task_id': 'x|t'})
