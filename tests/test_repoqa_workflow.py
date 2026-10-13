"""Provider-free checks of the checkout-based study orchestration."""
import json
from pathlib import Path
import sys

import pytest

from ctxbench.adapters.repoqa import workflow
from ctxbench.adaptive.recovery import sealed_read


def test_prepare_preserves_population_and_budgets(tmp_path, monkeypatch):
    payload = json.loads(Path('tests/fixtures/repoqa_surface_experiment.json').read_text())
    payload['dataset']['root'] = str(Path('datasets/repoqa').resolve())
    payload['scope']['instances'] = []
    payload['execution'] = {'repeats': 2}
    experiment = tmp_path / 'experiment.json'
    experiment.write_text(json.dumps(payload))
    # Exercise the documented offline fallback, without tokenizer downloads.
    monkeypatch.setitem(sys.modules, 'tiktoken', None)
    result = workflow.prepare(experiment=experiment, context_limit=200000,
                              output_reservation=2048, output=tmp_path)
    study = sealed_read(Path(result['prepared']))
    assert len(study['trials']) == 320
    assert len(study['requests']) == 160
    assert len(study['split']['calibration']) == 4
    assert all(len(order) == 64 for order in study['heldOut'].values())
    assert study['budget']['tokenizer'] == 'utf8-byte-upper-bound'
    assert all(t['params']['max_tokens'] == 2048 for t in study['trials'])
    workflow.verify_study(study)
    with pytest.raises(ValueError, match='fresh output'):
        workflow.prepare(experiment=experiment, context_limit=200000,
                         output_reservation=2048, output=tmp_path)


def test_missing_git_provenance_is_actionable(monkeypatch):
    import subprocess
    from ctxbench.adaptive import runner
    def missing(*args, **kwargs):
        raise subprocess.CalledProcessError(128, ['git'])
    monkeypatch.setattr(runner.subprocess, 'check_output', missing)
    with pytest.raises(RuntimeError, match='source checkout.*HEAD commit'):
        runner.source_identity()


def test_scorer_helpers_resolve_from_checkout(monkeypatch):
    from types import SimpleNamespace
    calls = []
    def score(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps(
            {'verdict': 'best_match', 'bestSimilarScore': 1}), stderr='')
    monkeypatch.setattr(workflow.subprocess, 'run', score)
    workflow.scorer_smoke()
    root = Path(__file__).resolve().parents[1]
    assert calls == [[str(root / 'tools/repoqa/repoqa_python'), str(root / 'tools/repoqa/score_response.py')]]


def test_missing_scorer_helpers_is_actionable(tmp_path, monkeypatch):
    from ctxbench.adapters.repoqa import evaluation
    monkeypatch.setattr(evaluation, '_repo_root', lambda: tmp_path)
    with pytest.raises(RuntimeError, match='scorer helpers missing.*source checkout'):
        workflow.scorer_smoke()


@pytest.mark.parametrize('changed', ['dataset', 'experiment', 'sources'])
def test_prepared_fingerprints_remain_required(tmp_path, monkeypatch, changed):
    experiment = tmp_path / 'experiment.json'
    experiment.write_text('{}')
    study = {'datasetRoot': str(tmp_path), 'datasetHash': 'dataset',
             'experimentPath': str(experiment), 'experimentHash': workflow.digest({}),
             'sources': {'revision': 'original'}}
    monkeypatch.setattr(workflow, 'tree_hash', lambda root: 'changed' if changed == 'dataset' else 'dataset')
    monkeypatch.setattr(workflow, 'source_identity', lambda: {'revision': 'changed' if changed == 'sources' else 'original'})
    if changed == 'experiment':
        experiment.write_text('{"changed": true}')
    with pytest.raises(ValueError, match='fingerprint|source revision'):
        workflow.verify_study(study)
