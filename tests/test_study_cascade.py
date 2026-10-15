"""Cascade policy: bounded within-request fallback on observed failures."""
import json
from pathlib import Path

import pytest

from ctxbench.adaptive.recovery import sealed_read
from ctxbench.adaptive.runner import error_result
from ctxbench.adaptive.study_runner import load_packets
from ctxbench.studies import study
from ctxbench.studies.models import Study
from tests.test_study_protocol import frozen, make_study, mock_execute  # noqa: F401  (fixture reuse)

PRIMARY, FALLBACK = 'local-mcp-repoqa-ops', 'inline-code-full'


def cascade_study(tmp_path, frozen, name='cascade', **options):
    definition = make_study(tmp_path, frozen, comparisons=[], policies={
        'cascade': {'type': 'cascade', 'primary': PRIMARY, 'fallbacks': [FALLBACK], **options}})
    return Path(study.prepare(definition=definition, output=tmp_path/name)['prepared'])


class Executor:
    """Primary fails with a step limit for chosen targets; records every execution."""
    def __init__(self, failing_targets, message='Local MCP strategy exceeded max_steps=8.'):
        self.failing, self.message, self.calls = set(failing_targets), message, []

    def __call__(self, trial, engine, **kwargs):
        self.calls.append((trial.instanceId, trial.configurationId, dict(trial.params)))
        if trial.configurationId == PRIMARY and trial.instanceId.rsplit('_ctx', 1)[0] in self.failing:
            return error_result(trial, self.message, '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z', 100)
        return mock_execute(trial, engine)


def run_episode(path, execution, **kwargs):
    plan = sealed_read(path)
    episode = plan['episodes'][0]
    study.episode(prepared=path, policy=episode['policyName'], scenario=episode['scenarioName'],
                  seed=episode['seed'], repeat=episode['repeat'], execution=execution, **kwargs)
    return plan, load_packets(path.parent/'episodes'/episode['id'])


def test_fallback_runs_only_after_trigger_failure(frozen, tmp_path):
    path = cascade_study(tmp_path, frozen)
    target = sealed_read(path)['split']['heldOut'][0]
    executor = Executor([target])
    plan, packets = run_episode(path, executor)
    for packet in packets:
        attempts = [a['configuration'] for a in packet['attempts']]
        failing = packet['instanceId'].startswith(target + '_ctx')
        assert attempts == ([PRIMARY, FALLBACK] if failing else [PRIMARY])
        assert packet['observation']['configuration'] == attempts[-1]
        assert packet['observation']['status'] == 'success'
        assert packet['decision']['schemaVersion'] == 4
        assert packet['decision']['finalConfiguration'] == attempts[-1]
        if failing:
            assert packet['decision']['fallbackReason'] == ['step-limit']
            # Failed primary usage is unknown, so the request total is a lower bound.
            assert packet['observation']['tokens'] == {'value': None, 'provenance': 'unavailable', 'knownPartial': 10}
            assert packet['observation']['durationMs'] == sum(a['durationMs'] for a in packet['attempts'])
    root = path.parent/'episodes'/plan['episodes'][0]['id']
    responses = [json.loads(line) for line in (root/'responses.jsonl').read_text().splitlines()]
    assert len(responses) == len(executor.calls) == len(packets) + sum(len(p['attempts']) > 1 for p in packets)
    assert len({row['trialId'] for row in responses}) == len(responses)


def test_non_trigger_failure_does_not_fall_back(frozen, tmp_path):
    path = cascade_study(tmp_path, frozen)
    target = sealed_read(path)['split']['heldOut'][0]
    plan, packets = run_episode(path, Executor([target], message='boom'))
    assert all(len(p['attempts']) == 1 for p in packets)
    assert any(p['observation']['status'] == 'error' for p in packets)


def test_primary_step_override_applies_only_to_primary(frozen, tmp_path):
    path = cascade_study(tmp_path, frozen, primaryMaxSteps=5)
    target = sealed_read(path)['split']['heldOut'][0]
    executor = Executor([target])
    run_episode(path, executor)
    assert {params.get('max_steps') for _, cid, params in executor.calls if cid == PRIMARY} == {5}
    assert {params.get('max_steps') for _, cid, params in executor.calls if cid == FALLBACK} == {None}


def test_source_memory_routes_later_requests_to_fallback(frozen, tmp_path):
    path = cascade_study(tmp_path, frozen, memory='source')
    plan = sealed_read(path)
    target = plan['split']['heldOut'][0]
    source = {item['instanceId']: item['repo'] for item in plan['index']}
    plan, packets = run_episode(path, Executor([target]))
    failing_repo = next(source[p['instanceId']] for p in packets if len(p['attempts']) > 1)
    first_failure = next(i for i, p in enumerate(packets) if len(p['attempts']) > 1)
    later = [p for p in packets[first_failure+1:] if source[p['instanceId']] == failing_repo]
    assert later and all(p['selection']['reason'] == 'source_memory' for p in later)
    assert all([a['configuration'] for a in p['attempts']] == [FALLBACK] for p in later)


class Crash(Exception):
    pass


def test_resume_between_attempts_keeps_primary(frozen, tmp_path):
    path = cascade_study(tmp_path, frozen)
    target = sealed_read(path)['split']['heldOut'][0]
    executor = Executor([target])
    def crash(stage, sequence):
        if stage == 'attempt_saved' and executor.calls[-1][1] == PRIMARY and \
                executor.calls[-1][0].startswith(target + '_ctx'):
            raise Crash()
    with pytest.raises(Crash):
        run_episode(path, executor, checkpoint=crash)
    interrupted = executor.calls[-1][0]
    plan, packets = run_episode(path, executor, resume=True)
    assert [cid for instance, cid, _ in executor.calls if instance == interrupted] == [PRIMARY, FALLBACK]
    packet = next(p for p in packets if p['instanceId'] == interrupted)
    assert packet['uncertainRetries'] == 0 and len(packet['attempts']) == 2


def test_crash_during_fallback_requires_explicit_retry(frozen, tmp_path):
    path = cascade_study(tmp_path, frozen)
    target = sealed_read(path)['split']['heldOut'][0]
    executor = Executor([target])
    started = []
    def crash(stage, sequence):
        if stage == 'attempt_started':
            started.append(sequence)
            if started.count(sequence) == 2:
                raise Crash()
    with pytest.raises(Crash):
        run_episode(path, executor, checkpoint=crash)
    with pytest.raises(ValueError, match='uncertain interrupted attempt'):
        run_episode(path, executor, resume=True)
    plan, packets = run_episode(path, executor, resume=True, retry_uncertain=True)
    packet = packets[started[-1]-1]
    assert packet['uncertainRetries'] == 1
    assert [a['configuration'] for a in packet['attempts']] == [PRIMARY, FALLBACK]
    assert packet['attempts'][1]['observation']['tokens']['value'] is None


def test_completed_cascade_replays_on_resume(frozen, tmp_path):
    path = cascade_study(tmp_path, frozen)
    target = sealed_read(path)['split']['heldOut'][0]
    run_episode(path, Executor([target]))
    run_episode(path, lambda *a, **kw: pytest.fail('reran a completed attempt'), resume=True)


def test_cascade_definitions_are_validated(frozen, tmp_path):
    base = {'baseline': str(frozen), 'seeds': [1], 'repeats': 1, 'scenarios': {'s': []}}
    with pytest.raises(ValueError, match='distinct from the primary'):
        Study.model_validate({**base, 'policies': {'c': {'type': 'cascade', 'primary': PRIMARY,
                                                          'fallbacks': [PRIMARY]}}})
    with pytest.raises(ValueError):
        Study.model_validate({**base, 'policies': {'c': {'type': 'cascade', 'primary': PRIMARY,
                                                          'fallbacks': [FALLBACK, 'other']}}})
    definition = make_study(tmp_path, frozen, comparisons=[], policies={
        'c': {'type': 'cascade', 'primary': 'missing', 'fallbacks': [FALLBACK]}})
    with pytest.raises(ValueError, match='unselected configuration'):
        study.prepare(definition=definition, output=tmp_path/'bad-cascade')


def test_analysis_counts_fallbacks_and_token_lower_bound(frozen, tmp_path):
    path = cascade_study(tmp_path, frozen)
    target = sealed_read(path)['split']['heldOut'][0]
    plan, packets = run_episode(path, Executor([target]))
    summary = study.analyze(path, bootstrap_replicates=10)['summaries'][0]
    fallbacks = sum(len(p['attempts']) > 1 for p in packets)
    assert summary['fallbacks'] == fallbacks > 0
    assert summary['tokenCoverage'] == len(packets) - fallbacks
    assert summary['tokensLowerBound'] == 10 * len(packets)
    assert summary['wastedTokensLowerBound'] == 0
    assert summary['success'] == len(packets)
