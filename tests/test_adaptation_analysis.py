from copy import deepcopy

import pytest

from ctxbench.adapters.repoqa.adaptation_analysis import (bootstrap, paired_differences, reaction, summarize,
                                                         uninterrupted_blocks, analyze_study)
from tests.test_adaptive_runner import episode, run


def row(policy='adaptive-router', request='r1', **updates):
    return {'policy': policy, 'scenario': 'degradation-recovery', 'seed': 1, 'requestId': request,
            'trialId': 'repeated-trial', 'target': 'py_1', 'language': 'python', 'sequenceIndex': 1,
            'status': 'success', 'durationMs': 100, 'tokens': 10, 'controllerDurationMs': 1,
            'deadlineMiss': False, 'passed': True, 'qualityAvailable': True,
            'normalConfiguration': 'inline-code-full', 'probe': False, 'interrupted': False,
            'uncertainRetries': 0, 'contextBytes': 100, 'sizeBin': 'small', **updates}


def test_all_request_denominator_and_missing_resource_coverage():
    rows = [row(), row(request='r2', status='error', passed=False, tokens=None),
            row(request='r3', status='unserved', passed=False, durationMs=None, tokens=None, deadlineMiss=None)]
    summary = summarize(rows)
    assert summary['allRequestPassRate'] == 1 / 3
    assert summary['tokenCoverage'] == 1 / 3
    assert summary['deadlineMissRate'] is None
    assert summary['knownTotalTokens'] == 10
    assert not summary['resourceTotalsComplete']
    rows[0]['uncertainRetries'] = 1
    summary = summarize(rows, {'events': [{'type': 'known-extra-usage', 'tokens': 5}]})
    assert summary['knownTotalTokens'] == 15
    assert summary['unknownPriorUsage'] is None
    assert summary['uncertainRepeatedAttempts'] == 1


def test_reaction_excludes_probe_and_censors():
    rows = [row(sequenceIndex=20), row(sequenceIndex=21, probe=True, normalConfiguration='local-mcp-repoqa-ops'),
            row(sequenceIndex=22), row(sequenceIndex=23, normalConfiguration='local-mcp-repoqa-ops')]
    assert reaction(rows, 21)['requestsUntilChange'] == 3
    assert reaction(rows[:3], 21)['censored']


def test_pairing_uses_episode_identity_and_group_bootstrap():
    rows = []
    for seed in (1, 2):
        for target, lang in (('py1', 'python'), ('py2', 'python'), ('go1', 'go')):
            for variant in range(4):
                identity = f'{target}-{variant}'
                rows.extend([row(seed=seed, target=target, language=lang, request=identity, tokens=8),
                             row(policy='frozen-router', seed=seed, target=target, language=lang, request=identity, tokens=10)])
    differences, missing = paired_differences(rows)
    assert len(differences) == 24 and missing == 0
    interval = bootstrap(differences, 'tokens', 100)
    assert interval['mean'] == interval['lower95'] == interval['upper95'] == -2
    assert interval['targets'] == 3
    assert interval == bootstrap(differences, 'tokens', 100)
    with pytest.raises(ValueError, match='duplicate'):
        paired_differences(rows + rows[:1])


def test_sensitivity_requires_complete_uninterrupted_blocks():
    arms = ('always-inline', 'always-local-mcp', 'frozen-router', 'adaptive-router')
    rows = [row(policy=p) for p in arms]
    assert len(uninterrupted_blocks(rows)) == 4
    assert uninterrupted_blocks(rows[:-1]) == []
    rows[0]['interrupted'] = True
    assert uninterrupted_blocks(rows) == []


def test_saved_episode_analysis_and_missing_quality(episode, tmp_path):
    episode = (episode[0], episode[1][:2], episode[2])
    for arm in ('always-inline', 'always-local-mcp', 'frozen-router', 'adaptive-router'):
        run(episode, tmp_path / 'episodes/stationary/20261001' / arm, arm)
    summary = analyze_study(tmp_path, bootstrap_replicates=20)
    assert len(summary['episodes']) == 4
    assert all(e['qualityCoverage'] == 0 for e in summary['episodes'])
    assert all(e['allRequestPassRate'] is None for e in summary['episodes'])
    assert summary['primary']['scenarios']['stationary']['tokens']['mean'] == 0
    assert (tmp_path / 'analysis/timeline.csv').exists()
    assert (tmp_path / 'analysis/summary.json').exists()


def test_completed_canonical_evaluation_is_outside_controller(episode, tmp_path, monkeypatch):
    import json
    import shutil
    from pathlib import Path
    from ctxbench.adapters.repoqa.evaluation import evaluate_response
    from ctxbench.benchmark.models import TrialResult
    from ctxbench.benchmark.results import serialize_evaluation_result
    from ctxbench.adaptive.recovery import project_rows
    from ctxbench.adapters.repoqa.adaptation_analysis import load_episode
    trials, workload, metadata = episode
    dataset = tmp_path / 'dataset'
    shutil.copytree(Path(trials[0].dataset.materialized_path), dataset)
    (dataset / 'context/repoqa-workspace-1/native_task.json').write_text(json.dumps(
        {'language': 'python', 'repo': 'fixture/repo', 'name': 'greet'}))
    (dataset / 'raw/repoqa-test.json').write_text(json.dumps(
        {'python': [{'repo': 'fixture/repo', 'content': {}, 'needles': []}]}))
    trials = [t.model_copy(update={'dataset': t.dataset.model_copy(update={'materialized_path': str(dataset)})}) for t in trials]
    def forbidden():
        raise AssertionError('controller invoked evaluation')
    monkeypatch.setattr('ctxbench.adapters.repoqa.evaluation._load_scorer', forbidden)
    output = tmp_path / 'episode'
    packets = run((trials, workload[:2], metadata), output)
    monkeypatch.setattr('ctxbench.adapters.repoqa.evaluation._load_scorer',
                        lambda: lambda *args: ('best_match', 'greet', 1.0))
    evaluations = [serialize_evaluation_result(evaluate_response(TrialResult.model_validate(packet['result'])),
                                               artifact_root=output, write_trace=False) for packet in packets]
    project_rows(output / 'evals.jsonl', evaluations)
    observations, _ = load_episode(output)
    assert summarize(observations)['allRequestPassRate'] == 1
    assert all(row['evaluationInputTokens'] is None for row in evaluations)


def test_bootstrap_retains_language_strata_and_target_variants():
    differences = []
    for target, language, delta in [('py1', 'python', 0), ('py2', 'python', 10), ('go1', 'go', 5)]:
        for seed in (1, 2):
            for variant in range(4):
                differences.append({'target': target, 'language': language, 'seed': seed,
                                    'tokens': delta, 'tokensProvenance': 'estimated'})
    interval = bootstrap(differences, 'tokens', 1000)
    assert interval['mean'] == 5
    assert interval['lower95'] == pytest.approx(5 / 3)
    assert interval['upper95'] == pytest.approx(25 / 3)
    assert interval['pairedRequests'] == 24
    assert interval['provenance'] == 'estimated'


def test_partial_usage_is_accounted_without_zero_for_missing_totals():
    summary = summarize([row(tokens=None, knownPartialTokens=5)])
    assert summary['knownTotalTokens'] == 5
    assert not summary['resourceTotalsComplete']
    assert summarize([row(tokens=None)])['knownTotalTokens'] is None
    assert summarize([])['allRequestPassRate'] is None


def _row(index, configuration, *, probe=False, tokens=1000, latency=2000.0, status='success', variant='2k'):
    return {'sequenceIndex': index, 'configuration': configuration, 'probe': probe, 'tokens': tokens,
            'tokenLowerBound': tokens, 'latencyMs': latency, 'status': status, 'variant': variant}


def _w2_rows(probes, returns_at, end_of_run=48, leave_at=19):
    """Inline before position leave_at, Direct after it; probes go to Inline; back on Inline from returns_at."""
    rows = []
    for i in range(1, end_of_run+1):
        if i in probes:
            rows.append(_row(i, 'inline', probe=True, **probes[i]))
        elif i < leave_at or (returns_at and i >= returns_at):
            rows.append(_row(i, 'inline'))
        else:
            rows.append(_row(i, 'direct'))
    return rows


W2 = [{'firstRequest': 1, 'lastRequest': 16}, {'firstRequest': 17, 'lastRequest': 32, 'disturbance': True},
      {'firstRequest': 33, 'lastRequest': 48}]
AP = {'type': 'blind-router', 'probeTriggers': ['periodic'], 'probeInterval': 8, 'signalTokens': None}
RATE = {'perRequest': 12000, 'window': 8}


def test_burst_details_qualifying_return_matches_the_schedule_prediction():
    from ctxbench.studies.study import _burst_details
    rows = _w2_rows({27: {'tokens': 48000, 'variant': '64k'}, 35: {'tokens': 4000}}, returns_at=36)
    [burst] = _burst_details(rows, W2, AP, 8000, RATE)
    assert (burst['reactionLag'], burst['recoveryLag'], burst['probesInside'], burst['rejectedAfter']) == (2, 3, 1, 0)
    assert burst['scheduleKept'] and burst['returnByProbe'] and burst['qualifying']
    assert burst['predictedRecoveryLag'] == 3 and burst['sustainedRecoveryLag'] == 3


def test_burst_details_rejected_probe_adds_an_interval_and_skipped_probe_breaks_the_schedule():
    from ctxbench.studies.study import _burst_details
    rejected = _w2_rows({27: {'tokens': 48000}, 35: {'tokens': 12900, 'variant': '16k'}, 43: {'tokens': 3000}},
                        returns_at=44)
    [burst] = _burst_details(rejected, W2, AP, 8000, RATE)
    assert burst['recoveryLag'] == 11 and burst['rejectedAfter'] == 1 and burst['predictedRecoveryLag'] == 11
    assert burst['rejectedAfterDetails'] == [{'sequenceIndex': 35, 'variant': '16k', 'reason': 'tokens'}]
    skipped = _w2_rows({27: {'tokens': 48000}, 39: {'tokens': 3000}}, returns_at=40)
    [burst] = _burst_details(skipped, W2, AP, 8000, RATE)
    assert burst['scheduleKept'] is False and burst['qualifying'] is False and 'predictedRecoveryLag' not in burst


def test_burst_details_forced_return_censoring_and_departure_before_the_burst():
    from ctxbench.studies.study import _burst_details
    forced = _w2_rows({27: {'tokens': 48000}}, returns_at=31)
    [burst] = _burst_details(forced, W2, AP, 8000, RATE)
    assert burst['returnByProbe'] is False and burst['qualifying'] is False and burst['recoveryLag'] == 0
    censored = _w2_rows({27: {'tokens': 48000}, 35: {'tokens': 13000}, 43: {'tokens': 13000}}, returns_at=None)
    [burst] = _burst_details(censored, W2, AP, 8000, RATE)
    assert burst['recoveryLag'] is None and burst['recoveryCensored'] and burst['rejectedAfter'] == 2
    early = _w2_rows({}, returns_at=None, leave_at=10)
    [burst] = _burst_details(early, W2, AP, 8000, RATE)
    assert burst['leftBefore'] and 'reactionLag' not in burst
    no_policy = _burst_details(_w2_rows({}, returns_at=33), W2, None, 8000, RATE)[0]
    assert no_policy['scheduleKept'] is None and no_policy['qualifying'] is None and no_policy['recoveryLag'] == 0


def test_rate_details_full_windows_magnitude_and_longest_run():
    from ctxbench.studies.study import _rate_details
    rows = [_row(i, 'inline', tokens=t) for i, t in enumerate([100000, 0, 0, 0, 30000, 30000, 30000, 0, 0, 0], 1)]
    details = _rate_details(rows, {'perRequest': 10000, 'window': 4})
    # Canonical means (window 4): 25k, 25k, 25k, 25k, 7.5k, 15k, 22.5k, 22.5k, 15k, 7.5k.
    assert details['fullWindowBudgetExcess'] == 5 and details['longestViolationRun'] == 4
    assert details['excessMagnitudeMax'] == 15000 and details['excessMagnitudeCumulative'] == 15000+5000+12500+12500+5000
