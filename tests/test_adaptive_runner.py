import json
from dataclasses import replace
from pathlib import Path

import pytest

from ctxbench.adapters.repoqa.package import RepoQADatasetAdapter
from ctxbench.adapters.repoqa.study import pair_trials
from ctxbench.adaptive.runner import EpisodeRequest, error_result, run_episode
from ctxbench.adaptive.sidecars import RunMetadata
from ctxbench.adaptive.types import Candidate, ContextFit, Provenance, RequestFeatures, SizeBin
from ctxbench.benchmark.models import DatasetProvenance, Experiment
from ctxbench.benchmark.runspec_generator import generate_runspecs
from ctxbench.benchmark.provisioning import validate_artifact_directory


@pytest.fixture
def episode(tmp_path):
    root = Path('tests/fixtures/repoqa_tools_dataset').resolve()
    data = json.loads(Path('tests/fixtures/repoqa_surface_experiment.json').read_text())
    data['execution'] = {'repeats': 64}
    trials = generate_runspecs(Experiment.model_validate(data), tmp_path, RepoQADatasetAdapter(root),
                              DatasetProvenance(id='ctxbench/repoqa', version='fixture', materialized_path=str(root)))
    workload = []
    for i, pair in enumerate(pair_trials(trials).values(), 1):
        candidates = tuple(Candidate(cid, True, ContextFit(10, 5, 100, Provenance.ESTIMATED)) for cid in pair)
        workload.append(EpisodeRequest(f'r{i}', RequestFeatures(i, 100, SizeBin.SMALL),
                                       tuple(t.trialId for t in pair.values()), candidates, 'target', 'python'))
    metadata = dict(policyVersion='2', seed=20261001, datasetProvenance={}, modelProvenance={},
                    configurationCatalog={}, latencyObjectiveMs=1000, injectionSchedule=(),
                    cachePolicy={}, codeRevision='fixture')
    return trials, workload, metadata


def execute(trial, engine, **kwargs):
    result = error_result(trial, 'placeholder', '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z', 1000)
    return result.model_copy(update={'status': 'success', 'errorMessage': None, 'response': 'code',
                                     'usage': {'totalTokens': 10}})


class Clock:
    def __init__(self):
        self.value = 0
    def __call__(self):
        self.value += 1
        return self.value


def run(episode, output, arm='adaptive-router', scenario='stationary', **kwargs):
    trials, workload, metadata = episode
    return run_episode(trials, workload, {}, arm, scenario, output,
                       metadata=RunMetadata(policy=arm, scenario=scenario, **metadata),
                       execution=execute, monotonic=Clock(), **kwargs)


@pytest.mark.parametrize('arm', ['always-inline', 'always-local-mcp', 'frozen-router', 'adaptive-router'])
@pytest.mark.parametrize('scenario', ['stationary', 'degradation-recovery'])
def test_complete_arms_and_canonical_artifacts(episode, tmp_path, arm, scenario):
    packets = run(episode, tmp_path / 'episode', arm, scenario)
    assert len(packets) == 64
    assert all(p['decision']['status'] == 'success' for p in packets)
    assert sum(p['decision']['decision']['probe'] for p in packets) == (6 if 'router' in arm else 0)
    validate_artifact_directory(tmp_path / 'episode')
    assert len((tmp_path / 'episode/responses.jsonl').read_text().splitlines()) == 64


def test_errors_and_unserved_are_final(episode, tmp_path):
    trials, workload, metadata = episode
    workload = workload[:2]
    workload[1] = replace(workload[1], candidates=tuple(replace(c, executable=False) for c in workload[1].candidates))
    def fail(*args, **kwargs):
        raise RuntimeError('setup failure')
    output = tmp_path / 'errors'
    options = dict(metadata=RunMetadata(policy='adaptive-router', scenario='stationary', **metadata), execution=fail)
    packets = run_episode(trials, workload, {}, 'adaptive-router', 'stationary', output, **options)
    assert [p['decision']['status'] for p in packets] == ['error', 'unserved']
    def forbidden(*args):
        raise AssertionError('completed outcomes must not execute')
    options['execution'] = forbidden
    assert run_episode(trials, workload, {}, 'adaptive-router', 'stationary', output, resume=True, **options) == packets


@pytest.mark.parametrize('stage', ['selection_saved', 'execution_started', 'execution_finished', 'outcome_saved',
                                  'trace_projection', 'trials_projection', 'responses_projection',
                                  'decisions_projection', 'controller-timings_projection'])
def test_interruption_and_replay(episode, tmp_path, stage):
    trials, workload, metadata = episode
    episode = (trials, workload[:12], metadata)
    fired = False
    def crash(name, index):
        nonlocal fired
        if not fired and name == stage and index == 10:
            fired = True
            raise KeyboardInterrupt('crash')
    with pytest.raises(KeyboardInterrupt):
        run(episode, tmp_path / 'resumed', checkpoint=crash)
    if stage in ('execution_started', 'execution_finished'):
        with pytest.raises(ValueError, match='uncertain'):
            run(episode, tmp_path / 'resumed', resume=True)
    resumed = run(episode, tmp_path / 'resumed', resume=True, retry_uncertain=True)
    fresh = run(episode, tmp_path / 'fresh')
    assert [p['selection'] for p in resumed] == [p['selection'] for p in fresh]
    assert [p['decision']['status'] for p in resumed] == [p['decision']['status'] for p in fresh]
    # Completed packet repairs never re-execute a provider call.
    assert sum(p['uncertainRetries'] for p in resumed) == (1 if stage in ('execution_started', 'execution_finished') else 0)


def test_changed_inputs_corruption_and_lock_rejected(episode, tmp_path):
    from ctxbench.adaptive.recovery import episode_lock
    trials, workload, metadata = episode
    episode = (trials, workload[:1], metadata)
    output = tmp_path / 'saved'
    run(episode, output)
    changed = (trials, [replace(workload[0], features=RequestFeatures(1, 200, SizeBin.SMALL))], metadata)
    with pytest.raises(ValueError, match='fingerprint'):
        run(changed, output, resume=True)
    with episode_lock(output):
        with pytest.raises(ValueError, match='active writer'):
            run(episode, output, resume=True)
    path = output / 'recovery/request-0001.json'
    data = json.loads(path.read_text())
    data['payload']['decision']['status'] = 'error'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='corrupt'):
        run(episode, output, resume=True)


def test_completed_projections_repaired_without_execution(episode, tmp_path, monkeypatch):
    episode = (episode[0], episode[1][:2], episode[2])
    output = tmp_path / 'saved'
    run(episode, output)
    (output / 'responses.jsonl').unlink()
    (output / 'traces/executions').joinpath(episode[1][0].trial_ids[0] + '.json').unlink()
    def forbidden(*args, **kwargs):
        raise AssertionError('executed')
    monkeypatch.setattr(__import__('sys').modules[__name__], 'execute', forbidden)
    assert len(run(episode, output, resume=True)) == 2
    path = output / 'decisions.jsonl'
    path.write_text(path.read_text() * 2)
    with pytest.raises(ValueError, match='duplicate'):
        run(episode, output, resume=True)
