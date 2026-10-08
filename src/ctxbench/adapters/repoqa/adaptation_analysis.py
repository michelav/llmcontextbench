"""Analysis from completed canonical episode artifacts, without model/scorer calls."""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean

from ctxbench.adaptive.calibration import quantile
from ctxbench.adaptive.recovery import read, sealed_read, write
from ctxbench.adaptive.sidecars import DecisionSidecar
from ctxbench.benchmark.models import TrialResult, TrialSpec
from ctxbench.ai.models.usage import account_tokens
from ctxbench.benchmark.provisioning import validate_artifact_directory

ARMS = {'always-inline', 'always-local-mcp', 'frozen-router', 'adaptive-router'}


def rows(path):
    if not path.exists():
        return []
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def unique(rows_, key):
    result = {}
    for row in rows_:
        identity = row[key]
        if identity in result:
            raise ValueError(f'duplicate {key} in analysis inputs')
        result[identity] = row
    return result


def load_episode(root):
    root = Path(root)
    validate_artifact_directory(root)
    identity = sealed_read(root / 'recovery/identity.json')
    workload = identity['workload']
    decisions = rows(root / 'decisions.jsonl')
    timings = unique(rows(root / 'controller-timings.jsonl'), 'requestId')
    trials = unique(rows(root / 'trials.jsonl'), 'trialId')
    responses = unique(rows(root / 'responses.jsonl'), 'trialId')
    evaluations = unique(rows(root / 'evals.jsonl'), 'trialId')
    if len(decisions) != len(workload):
        raise ValueError('analysis requires a completed episode')
    lifecycle = read(root / 'lifecycle.json')
    interrupted = any(s['resumed'] for s in lifecycle['sessions'])
    meta = read(root / 'adaptive-run.json')
    if meta != identity['metadata'] or read(root / 'manifest.json') != identity['manifest']:
        raise ValueError('run metadata/manifest projection mismatch')
    observations = []
    for index, (scheduled, row) in enumerate(zip(workload, decisions), 1):
        decision = DecisionSidecar.model_validate(row)
        packet = sealed_read(root / f'recovery/request-{index:04d}.json')
        if packet['state'] != 'completed' or packet['decision'] != row:
            raise ValueError('decision projection does not match completed recovery packet')
        if decision.request_id != scheduled['request_id'] or decision.decision.sequence_index != index:
            raise ValueError('analysis request order mismatch')
        trial_id = decision.trial_id
        passed, quality_available = False, True
        tool_calls, known_partial = None, None
        if trial_id:
            if trial_id not in trials or trial_id not in responses:
                raise ValueError('missing canonical trial/response')
            trial, response = trials[trial_id], responses[trial_id]
            expected_trial = TrialSpec.model_validate(packet['trial']).to_persisted_artifact()
            expected_response = TrialResult.model_validate(packet['result']).to_persisted_artifact(trace_ref=response.get('traceRef'))
            if trial != expected_trial or response != expected_response:
                raise ValueError('canonical projection differs from recovery packet')
            if trial['trialId'] != packet['trial']['trialId'] or response['status'] != decision.status:
                raise ValueError('canonical outcome mismatch')
            if response['configurationId'] != decision.decision.selected_configuration:
                raise ValueError('canonical configuration mismatch')
            trace_ref = response.get('traceRef')
            if trace_ref:
                trace = read(root / trace_ref)['trace']
                if trace != packet['result']['trace']:
                    raise ValueError('trace projection mismatch')
                tool_calls = len(trace.get('toolCalls', []))
            metrics = packet['result']['trace']['aiTrace'].get('metrics', {})
            _, _, known_partial = account_tokens(response['provider'], response['usage'].get('totalTokens'),
                model_calls=metrics.get('modelCalls'), raw_response=packet['result']['trace']['rawResponse'],
                partial_total=metrics.get('totalTokens'), missing_total_estimate=metrics.get('totalTokensEstimated'))
            if decision.status == 'success':
                evaluation = evaluations.get(trial_id)
                if evaluation and evaluation.get('evaluationMethod') != 'repoqa-scorer':
                    raise ValueError('only deterministic RepoQA evaluation is supported')
                quality_available = bool(evaluation and isinstance((evaluation.get('outcome') or {}).get('passed'), bool))
                passed = bool(evaluation['outcome']['passed']) if quality_available else None
        observation = {'episode': str(root), 'policy': meta['policy'], 'scenario': meta['scenario'],
            'seed': meta['seed'], 'requestId': scheduled['request_id'], 'trialId': trial_id,
            'target': scheduled['target'], 'language': scheduled['language'], 'sequenceIndex': index,
            'status': decision.status, 'configuration': decision.decision.selected_configuration,
            'normalConfiguration': decision.decision.normal_configuration, 'probe': decision.decision.probe,
            'durationMs': decision.end_to_end_duration_ms.value, 'tokens': decision.tokens.value,
            'knownPartialTokens': known_partial if decision.tokens.value is None else None,
            'durationProvenance': decision.end_to_end_duration_ms.provenance,
            'tokensProvenance': decision.tokens.provenance,
            'controllerDurationMs': timings[decision.request_id]['controllerDurationMs'],
            'deadlineMiss': (decision.end_to_end_duration_ms.value > meta['latencyObjectiveMs']
                             if decision.end_to_end_duration_ms.value is not None else None),
            'passed': passed, 'qualityAvailable': quality_available, 'toolCalls': tool_calls,
            'objectiveMs': meta['latencyObjectiveMs'], 'contextBytes': decision.decision.features.context_bytes, 'sizeBin': decision.decision.features.size_bin,
            'interrupted': interrupted, 'uncertainRetries': packet['uncertainRetries']}
        observations.append(observation)
    selected = {o['trialId'] for o in observations if o['trialId']}
    if set(trials) != selected or set(responses) != selected or not set(evaluations) <= selected:
        raise ValueError('unexpected canonical identities')
    return observations, lifecycle


def reaction(rows_, start):
    entry = next((r['normalConfiguration'] for r in rows_ if r['sequenceIndex'] == start - 1), None)
    stop = 44 if start == 21 else 64
    change = next((r['sequenceIndex'] for r in rows_ if start <= r['sequenceIndex'] <= stop
                   and not r['probe'] and r['normalConfiguration'] is not None
                   and r['normalConfiguration'] != entry), None)
    if entry is None:
        change = None
    return {'phaseStart': start, 'entryIncumbent': entry,
            'requestsUntilChange': change - start + 1 if change is not None else None,
            'censored': change is None, 'observationWindowRequests': stop - start + 1}


def summarize(rows_, lifecycle=None):
    count = len(rows_)
    durations = [r['durationMs'] for r in rows_ if r['durationMs'] is not None]
    tokens = [r['tokens'] for r in rows_ if r['tokens'] is not None]
    quality_count = sum(r['qualityAvailable'] for r in rows_)
    retries = sum(r['uncertainRetries'] for r in rows_)
    events = (lifecycle or {}).get('events', [])
    extra_values = [e['tokens'] for e in events if e.get('type') == 'known-extra-usage' and e.get('tokens') is not None]
    known_extra = sum(extra_values)
    partial_values = [r['knownPartialTokens'] for r in rows_ if r.get('knownPartialTokens') is not None]
    known_total = sum(tokens + partial_values + extra_values) if tokens or partial_values or extra_values else None
    misses = sum(r['deadlineMiss'] is True for r in rows_)
    previous = None
    switches = 0
    for r in rows_:
        current = r['normalConfiguration']
        if current is not None:
            switches += previous is not None and previous != current
            previous = current
    return {'metricProvenance': {'latencyQuantiles': 'derived', 'rates': 'derived',
                                'knownTotalTokens': 'unavailable' if known_total is None else 'estimated' if any(r.get('tokensProvenance') == 'estimated' for r in rows_) else 'derived',
                                'controllerMeanMs': 'derived', 'reaction': 'derived'},
            'scheduledRequests': count, 'errors': sum(r['status'] == 'error' for r in rows_),
            'unserved': sum(r['status'] == 'unserved' for r in rows_),
            'deadlineMisses': misses, 'deadlineMissRate': misses / count if count and len(durations) == count else None,
            'measuredDeadlineMissRate': misses / len(durations) if durations else None,
            'timingCoverage': len(durations) / count if count else 0,
            'allRequestPassRate': sum(r['passed'] is True for r in rows_) / count if count and quality_count == count else None,
            'qualityCoverage': quality_count / count if count else 0,
            'knownPasses': sum(r['passed'] is True for r in rows_),
            'p50Ms': quantile(durations, .5) if durations else None,
            'p95Ms': quantile(durations, .95) if durations else None,
            'knownTotalTokens': known_total, 'knownPartialTokens': sum(partial_values) if partial_values else None, 'tokenCoverage': len(tokens) / count if count else 0,
            'resourceTotalsComplete': len(tokens) == count and retries == 0,
            'knownExtraTokens': known_extra, 'uncertainRepeatedAttempts': retries,
            'unknownPriorUsage': None if retries else 0,
            'unknownPriorUsageProvenance': 'unavailable' if retries else 'derived',
            'controllerMeanMs': mean(r['controllerDurationMs'] for r in rows_) if count else None,
            'normalSwitches': switches, 'probes': sum(r['probe'] for r in rows_),
            'interrupted': any(r['interrupted'] for r in rows_),
            'reaction': [reaction(rows_, start) for start in (21, 45)] if rows_ and rows_[0]['scenario'] == 'degradation-recovery' else []}


def paired_differences(all_rows):
    pairs = defaultdict(dict)
    for row in all_rows:
        if row['policy'] in ('adaptive-router', 'frozen-router'):
            key = (row['scenario'], row['seed'], row['requestId'])
            if row['policy'] in pairs[key]:
                raise ValueError('duplicate episode/request identity')
            pairs[key][row['policy']] = row
    differences = []
    missing = 0
    for key, pair in sorted(pairs.items()):
        if len(pair) != 2:
            missing += 1
            continue
        adaptive, frozen = pair['adaptive-router'], pair['frozen-router']
        if (adaptive['target'], adaptive['language'], adaptive['contextBytes'], adaptive['sizeBin'], adaptive['sequenceIndex']) != (frozen['target'], frozen['language'], frozen['contextBytes'], frozen['sizeBin'], frozen['sequenceIndex']):
            raise ValueError('paired target/language mismatch')
        result = {'scenario': key[0], 'seed': key[1], 'requestId': key[2],
                  'target': adaptive['target'], 'language': adaptive['language']}
        for metric in ('deadlineMiss', 'durationMs', 'tokens', 'passed'):
            a, f = adaptive[metric], frozen[metric]
            result[metric] = float(a) - float(f) if a is not None and f is not None else None
        result['tokensProvenance'] = ('unavailable' if result['tokens'] is None else 'estimated'
            if 'estimated' in (adaptive.get('tokensProvenance'), frozen.get('tokensProvenance')) else 'derived')
        differences.append(result)
    return differences, missing


def bootstrap(differences, metric, replicates=10000, seed=20260929):
    if replicates <= 0:
        raise ValueError('bootstrap replicates must be positive')
    groups = defaultdict(lambda: defaultdict(list))
    for row in differences:
        if row[metric] is not None:
            groups[row['language']][row['target']].append(row[metric])
    if not groups:
        return {'mean': None, 'lower95': None, 'upper95': None, 'pairedRequests': 0, 'targets': 0}
    languages = [list(sorted(targets.items())) for _, targets in sorted(groups.items())]
    rng = random.Random(seed)
    samples = []
    for _ in range(replicates):
        values = []
        for targets in languages:
            for _ in targets:
                values.extend(rng.choice(targets)[1])
        samples.append(mean(values))
    observed = [r[metric] for r in differences if r[metric] is not None]
    # Percentile interval over signed differences (latency/token values can be negative).
    ordered = sorted(samples)
    import math
    return {'mean': mean(observed), 'lower95': ordered[max(0, math.ceil(.025 * replicates) - 1)],
            'upper95': ordered[max(0, math.ceil(.975 * replicates) - 1)],
            'pairedRequests': len(observed), 'targets': sum(len(g) for g in languages),
            'replicates': replicates, 'seed': seed, 'resamplingUnit': 'target-within-language',
            'provenance': 'estimated' if metric == 'tokens' and any(r.get('tokensProvenance') == 'estimated' for r in differences) else 'derived'}


def uninterrupted_blocks(all_rows):
    blocks = defaultdict(lambda: defaultdict(list))
    for row in all_rows:
        blocks[(row['scenario'], row['seed'])][row['policy']].append(row)
    retained = []
    for block in blocks.values():
        if set(block) == ARMS and not any(r['interrupted'] for group in block.values() for r in group):
            schedules = [{r['requestId'] for r in group} for group in block.values()]
            if all(s == schedules[0] for s in schedules):
                retained.extend(r for group in block.values() for r in group)
    return retained


def analyze_study(root, *, bootstrap_replicates=10000):
    root = Path(root)
    all_rows, episodes = [], []
    seen_episodes, study_fingerprints = set(), {}
    for path in sorted((root / 'episodes').glob('*/*/*/adaptive-run.json')):
        episode_rows, lifecycle = load_episode(path.parent)
        identity = sealed_read(path.parent / 'recovery/identity.json')
        metadata = identity['metadata']
        episode_key = (metadata['scenario'], metadata['seed'], metadata['policy'])
        if episode_key in seen_episodes:
            raise ValueError('duplicate episode identity')
        seen_episodes.add(episode_key)
        block = episode_key[:2]
        catalog = []
        for trial in identity['catalog']:
            trial = {**trial, 'params': {k: v for k, v in trial['params'].items() if k != 'prompt_cache_key'}}
            catalog.append(trial)
        fingerprint = {'calibration': identity['calibration'], 'policyConfig': identity['policyConfig'],
                       'workload': identity['workload'], 'catalog': catalog, 'sources': identity['sources'],
                       'dataset': metadata['datasetProvenance'], 'model': metadata['modelProvenance'],
                       'injection': metadata['injectionSchedule']}
        if block in study_fingerprints and study_fingerprints[block] != fingerprint:
            raise ValueError('comparison block has mismatched study inputs')
        study_fingerprints[block] = fingerprint
        all_rows.extend(episode_rows)
        episodes.append({'episode': str(path.parent), 'policy': episode_rows[0]['policy'],
                         'scenario': episode_rows[0]['scenario'], 'seed': episode_rows[0]['seed'],
                         **summarize(episode_rows, lifecycle), 'sessions': lifecycle['sessions']})
    if not episodes:
        raise ValueError('no completed episodes found')
    def comparisons(rows_):
        differences, missing = paired_differences(rows_)
        return {'unpairedRequests': missing, 'scenarios': {scenario: {
            metric: bootstrap([r for r in differences if r['scenario'] == scenario], metric, bootstrap_replicates)
            for metric in ('deadlineMiss', 'durationMs', 'tokens', 'passed')}
            for scenario in sorted({r['scenario'] for r in differences})}}
    summary = {'schemaVersion': 1, 'episodes': episodes, 'primary': comparisons(all_rows),
               'uninterruptedCompleteBlocks': comparisons(uninterrupted_blocks(all_rows)),
               'limits': ['Downtime is separate from completed request duration.',
                          'Resumed controller state does not recreate provider/cache/rate-limit conditions.',
                          'Missing metrics and uncertain prior usage leave resource totals incomplete.']}
    destination = root / 'analysis'
    destination.mkdir(parents=True, exist_ok=True)
    summary['timelinePlots'] = plot_timelines(destination, all_rows)
    write(destination / 'summary.json', summary)
    from ctxbench.adaptive.recovery import atomic_text
    atomic_text(destination / 'timeline.jsonl', ''.join(json.dumps(row, sort_keys=True) + '\n' for row in all_rows))
    # Standalone human-readable timelines, with no plotting dependencies.
    import csv
    import io
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(all_rows[0]))
    writer.writeheader()
    writer.writerows(all_rows)
    atomic_text(destination / 'timeline.csv', stream.getvalue())
    return summary


def plot_timelines(destination, all_rows):
    """Optional standalone scientific plots from saved observations."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return {'provenance': 'unavailable', 'reason': 'matplotlib is not installed; CSV/JSONL timelines remain available'}
    grouped = defaultdict(list)
    for row in all_rows:
        grouped[(row['scenario'], row['seed'], row['policy'])].append(row)
    files = []
    for (scenario, seed, policy), group in sorted(grouped.items()):
        fig, (latency, routing) = plt.subplots(2, 1, figsize=(10, 4.5), sharex=True,
                                              gridspec_kw={'height_ratios': [3, 1]}, layout='constrained')
        for cid, color, label in [('inline-code-full', '#2166ac', 'Inline'),
                                  ('local-mcp-repoqa-ops', '#b35806', 'Local MCP')]:
            selected = [r for r in group if r['configuration'] == cid and r['durationMs'] is not None]
            latency.scatter([r['sequenceIndex'] for r in selected], [r['durationMs'] for r in selected],
                            color=color, s=24, label=label)
        latency.axhline(group[0]['objectiveMs'], color='#555555', linestyle='--', label='Objective')
        routing.step([r['sequenceIndex'] for r in group],
                     [0 if r['normalConfiguration'] == 'inline-code-full' else 1
                      if r['normalConfiguration'] == 'local-mcp-repoqa-ops' else float('nan') for r in group],
                     where='post', color='#333333')
        probes = [r for r in group if r['probe']]
        routing.scatter([r['sequenceIndex'] for r in probes],
                        [0 if r['configuration'] == 'inline-code-full' else 1 for r in probes],
                        marker='x', color='#762a83', label='Probe')
        if scenario == 'degradation-recovery':
            for axis in (latency, routing):
                axis.axvspan(20.5, 44.5, color='#fddbc7', alpha=.35)
        routing.set_yticks([0, 1], ['Inline', 'Local MCP'])
        routing.set_xlabel('Scheduled request index')
        latency.set_ylabel('End-to-end duration (ms)')
        latency.legend(loc='upper left', fontsize=8)
        latency.set_title(f'{policy} · {scenario} · seed {seed}' + (' · resumed' if any(r['interrupted'] for r in group) else ''))
        path = destination / f'timeline-{scenario}-{seed}-{policy}.svg'
        fig.savefig(path)
        plt.close(fig)
        files.append(str(path))
    return {'provenance': 'derived', 'files': files}
