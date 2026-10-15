"""Provider-free replay: drive the real study Controller over resampled observations.

Replay supports debugging and parameter selection, not claims. Outcomes are drawn
from recorded calibration observations (never held-out evaluation data unless a
debug pool is requested) and disturbances are applied analytically.
"""
import json
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean

from pydantic import TypeAdapter

from ctxbench.adapters.repoqa.study import digest, ordered_workload
from ctxbench.adaptive.recovery import sealed_read, write
from ctxbench.adaptive.study_policy import Controller
from ctxbench.adaptive.study_runner import quota_wait_seconds
from .models import Effect, Policy

VERSION = 1
POLICIES = TypeAdapter(dict[str, Policy])
EFFECTS = TypeAdapter(list[Effect])
DEFAULT_MAX_STEPS = 8


def load_pool(plan):
    """Calibration observations keyed by (configuration, size bin), with tool calls and steps joined."""
    baseline_path = Path(plan['baselinePath'])
    frozen = sealed_read(baseline_path)
    metrics = {}
    for episode in {row['episode'] for row in frozen['observations']}:
        responses = baseline_path.parent / 'episodes' / episode / 'responses.jsonl'
        if responses.is_file():
            for line in responses.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    metrics[row['trialId']] = row.get('metricsSummary') or {}
    pool = defaultdict(list)
    for row in frozen['observations']:
        summary = metrics.get(row['trialId'], {})
        tokens = row['tokens']
        pool[(row['configuration'], row['sizeBin'])].append({
            'status': row['status'], 'durationMs': row['durationMs'], 'failures': list(row['failures']),
            'tokens': tokens['value'] if tokens['value'] is not None else tokens.get('knownPartial') or 0,
            'tokensKnown': tokens['value'] is not None, 'passed': row.get('passed') is True,
            'toolCalls': summary.get('toolCalls') or 0, 'steps': summary.get('steps') or 1})
    return dict(pool)


def _apply_effects(sample, cid, position, effects, rng):
    """Analytic disturbance model; the fault model is an explicit assumption (one extra step per fault)."""
    outcome = dict(sample, failures=list(sample['failures']), faults=0)
    for effect in effects:
        if not effect['firstRequest'] <= position <= effect['lastRequest']:
            continue
        kind = effect.get('kind', 'delay')
        if kind == 'delay' and effect['configuration'] == cid:
            calls = 1 if effect['scope'] == 'request' else outcome['toolCalls']
            outcome['durationMs'] += effect['delayMs']*calls
        elif kind == 'fault' and effect['configuration'] == cid and outcome['toolCalls']:
            faults = sum(rng.random() < effect['toolErrorRate'] for _ in range(outcome['toolCalls']))
            if faults:
                per_step = outcome['durationMs']/max(1, outcome['steps'])
                per_step_tokens = outcome['tokens']/max(1, outcome['steps'])
                outcome['durationMs'] += faults*per_step
                outcome['tokens'] += faults*per_step_tokens
                outcome['faults'] = faults
                if outcome['steps']+faults > DEFAULT_MAX_STEPS and outcome['status'] == 'success':
                    outcome['status'], outcome['failures'], outcome['passed'] = 'error', ['step-limit'], False
    return outcome


def simulate(plan, episode, effects, pool, rng):
    """One synthetic episode. Returns per-request rows using the live Controller code path."""
    controller = Controller(plan, episode)
    clock, quota_log, rows = 0.0, [], []
    quotas = [e for e in effects if e.get('kind') == 'token-quota']
    for index, instance in enumerate(episode['workload']):
        size = plan['requests'][instance]['sizeBin']
        selection = controller.decide(index)
        attempts, cid = [], selection['configuration']
        while cid is not None:
            active = [q['tokensPerMinute'] for q in quotas if q['firstRequest'] <= index+1 <= q['lastRequest']]
            wait = quota_wait_seconds(quota_log, clock, min(active)) if active else 0.0
            sample = rng.choice(pool[(cid, size)])
            outcome = _apply_effects(sample, cid, index+1, effects, rng)
            duration = outcome['durationMs'] + wait*1000
            clock += duration/1000
            quota_log.append((clock, outcome['tokens']))
            observation = {'configuration': cid, 'sizeBin': size, 'status': outcome['status'],
                           'durationMs': duration, 'failures': outcome['failures'], 'sequenceIndex': index+1,
                           'tokens': {'value': outcome['tokens'] if outcome['tokensKnown'] else None,
                                      'provenance': 'derived', 'knownPartial': outcome['tokens']}}
            controller.observe(observation)
            attempts.append({**observation, 'quotaWaitMs': wait*1000, 'faults': outcome['faults'],
                             'passed': outcome['passed']})
            fallback = controller.decide_fallback(index, observation) if len(attempts) == 1 else None
            cid = fallback['configuration'] if fallback else None
        final = attempts[-1] if attempts else None
        rows.append({'sequenceIndex': index+1, 'sizeBin': size, **selection,
                     'finalConfiguration': final['configuration'] if final else None,
                     'status': final['status'] if final else 'unserved',
                     'passed': bool(final and final['passed']),
                     'durationMs': sum(a['durationMs'] for a in attempts) if attempts else None,
                     'tokensLowerBound': sum(a['tokens']['knownPartial'] for a in attempts),
                     'attempts': len(attempts)})
    return rows


def _lags(rows, effects):
    """Requests from disturbance onset to the first non-probe switch away, and from its end to the first return."""
    result = []
    routed = {r['sequenceIndex']: r['configuration'] for r in rows if not r['probe'] and r['configuration']}
    for effect in effects:
        degraded = effect.get('configuration')
        if not degraded:
            continue
        start, end = effect['firstRequest'], effect['lastRequest']
        before = [routed[i] for i in range(max(1, start-5), start) if i in routed]
        if degraded not in before:
            continue
        away = next((i for i in range(start, end+1) if routed.get(i, degraded) != degraded), None)
        back = next((i for i in range(end+1, len(rows)+1) if routed.get(i) == degraded), None)
        result.append({'configuration': degraded, 'reactionLag': None if away is None else away-start,
                       'recoveryLag': None if back is None else back-end-1})
    return result


def summarize(rows, limit, effects):
    durations = [r['durationMs'] for r in rows if r['durationMs'] is not None]
    routed = [r['configuration'] for r in rows if not r['probe'] and r['configuration']]
    ordered = sorted(durations)
    return {'requests': len(rows),
            'deadlineMisses': sum(d > limit for d in durations) if limit is not None else None,
            'failures': sum(r['status'] not in ('success', 'unserved') for r in rows),
            'passRate': mean(r['passed'] for r in rows) if rows else None,
            'unserved': sum(r['status'] == 'unserved' for r in rows),
            'meanLatencyMs': mean(durations) if durations else None,
            'p95LatencyMs': ordered[max(0, -(-95*len(ordered)//100)-1)] if ordered else None,
            'tokensLowerBound': sum(r['tokensLowerBound'] for r in rows),
            'fallbacks': sum(r['attempts'] > 1 for r in rows),
            'probes': sum(bool(r['probe']) for r in rows),
            'switches': sum(a != b for a, b in zip(routed, routed[1:])),
            'lags': _lags(rows, effects)}


def plan_from_baseline(path, configurations=None, definition=None):
    """Replay plan built directly from a frozen baseline (read-only; no source verification needed)."""
    from .baseline import file_hash
    from .study import _calibration_size_mix, _latency_quantiles, _token_quantiles
    path = Path(path).resolve()
    frozen = sealed_read(path)
    parent = frozen['plan']
    selected = list(configurations or parent['configurations'])
    if any(cid not in parent['configurations'] for cid in selected):
        raise ValueError('unknown configuration subset')
    return {'kind': 'replay-plan', 'definition': dict(definition or {}), 'baselinePath': str(path),
            'baselineDigest': file_hash(path), 'configurations': selected, 'requests': parent['requests'],
            'index': parent['index'], 'split': parent['split'],
            'estimates': {cid: frozen['estimates'][cid] for cid in selected},
            'quality': {cid: frozen['quality'][cid] for cid in selected},
            'tokenQuantiles': _token_quantiles(frozen, selected),
            'latencyQuantiles': _latency_quantiles(frozen, selected),
            'calibrationSizeMix': _calibration_size_mix(parent)}


def replay(*, grid, prepared=None, baseline=None, output=None, replicates=None):
    """Run every grid point × policy × seed × replicate; report opportunity and capture per point."""
    spec = json.loads(Path(grid).read_text())
    if spec.get('schemaVersion') != VERSION:
        raise ValueError('unsupported replay grid version')
    if (prepared is None) == (baseline is None):
        raise ValueError('replay requires exactly one of prepared or baseline')
    if baseline is not None:
        plan = plan_from_baseline(baseline, spec.get('configurations'), spec.get('base'))
    else:
        path = Path(prepared).resolve()
        plan = sealed_read(path if path.is_file() else path/'prepared.json')
        plan = {**plan, 'definition': {**plan['definition'], **spec.get('base', {})}}
    policies = {name: policy.model_dump() for name, policy in POLICIES.validate_python(spec['policies']).items()}
    pool = load_pool(plan)
    missing = sorted({cid for cid in plan['configurations'] for size in plan['estimates'][cid]
                      if not pool.get((cid, size))})
    if missing:
        raise ValueError(f'calibration pool lacks observations for {missing}')
    metric = spec.get('metric', 'deadlineMisses')
    targets = spec.get('targets') or plan['split']['heldOut']
    replicates = replicates or spec.get('replicates', 1)
    points = []
    for point in spec['points']:
        effects = [e.model_dump() for e in EFFECTS.validate_python(point.get('effects', []))]
        definition = {**plan['definition'], **{k: point[k] for k in ('latencyLimitMs', 'tokenBudget') if k in point}}
        point_plan = {**plan, 'definition': definition}
        # A point may override policies, e.g. a schedule oracle matching its own disturbance.
        overrides = {name: policy.model_dump()
                     for name, policy in POLICIES.validate_python(point.get('policies', {})).items()}
        point_policies = {**policies, **overrides}
        results = defaultdict(list)
        for seed in spec['seeds']:
            workload = [r['instanceId'] for r in ordered_workload(plan['index'], targets, seed)]
            for replicate in range(replicates):
                for name, policy in point_policies.items():
                    episode = {'policyName': name, 'scenarioName': point['name'], 'seed': seed,
                               'repeat': replicate+1, 'workload': workload, 'policy': policy, 'scenario': effects,
                               'id': digest([point['name'], name, seed, replicate])[:24]}
                    # Identical draws across policies at the same seed and replicate.
                    rng = random.Random(f"{spec.get('seed', 0)}:{point['name']}:{seed}:{replicate}")
                    rows = simulate(point_plan, episode, effects, pool, rng)
                    results[name].append(summarize(rows, definition.get('latencyLimitMs'), effects))
        aggregate = {name: _aggregate(values) for name, values in results.items()}
        points.append({'name': point['name'], 'latencyLimitMs': definition.get('latencyLimitMs'),
                       'tokenBudget': definition.get('tokenBudget'), 'effects': effects,
                       'policies': aggregate,
                       **_opportunity(aggregate, point_policies, metric, spec.get('reference'))})
    report = {'schemaVersion': VERSION, 'kind': 'replay', 'provenance': 'estimated',
              'pool': 'calibration', 'heldOutDebug': False, 'metric': metric,
              'baselineDigest': plan['baselineDigest'], 'seeds': spec['seeds'], 'replicates': replicates,
              'points': points}
    if output:
        write(Path(output), report)
    return report


def _aggregate(values):
    keys = [k for k in values[0] if k != 'lags' and values[0][k] is not None]
    lags = [lag for v in values for lag in v['lags']]
    summary = {k: mean(v[k] for v in values) for k in keys}
    summary['reactionLag'] = _mean_known(lag['reactionLag'] for lag in lags)
    summary['recoveryLag'] = _mean_known(lag['recoveryLag'] for lag in lags)
    summary['episodes'] = len(values)
    return summary


def _mean_known(values):
    known = [v for v in values if v is not None]
    return mean(known) if known else None


def _opportunity(aggregate, policies, metric, reference=None):
    """Opportunity = reference − schedule oracle; capture = (reference − policy) / opportunity.

    The reference defaults to the non-adapting router (same catalogue, no feedback), so
    capture measures what runtime feedback recovers of the oracle's advantage. Fixed arms
    are reported for the cost side of the trade-off but are not the reference."""
    if reference is None:
        reference = next((n for n, p in policies.items() if p['type'] == 'router' and not p['adaptive']), None)
    oracle = [a[metric] for n, a in aggregate.items() if policies[n]['type'] == 'schedule' and metric in a]
    fixed = {n: a[metric] for n, a in aggregate.items() if policies[n]['type'] == 'fixed' and metric in a}
    result = {'reference': reference, 'bestFixed': min(fixed, key=fixed.get) if fixed else None,
              'opportunity': None, 'capture': {}}
    if reference not in aggregate or not oracle:
        return result
    opportunity = aggregate[reference][metric]-min(oracle)
    result['opportunity'] = opportunity
    result['capture'] = {n: ((aggregate[reference][metric]-a[metric])/opportunity if opportunity > 0 else None)
                         for n, a in aggregate.items()
                         if policies[n]['type'] not in ('fixed', 'schedule') and n != reference and metric in a}
    return result


def counterfactual_cascade(*, study_dir, primary, fallback):
    """Pair two fixed arms by seed and request: run `primary`, and `fallback` only where primary failed.

    Held-out exploratory evidence: it reuses recorded held-out executions."""
    root = Path(study_dir)
    plan = sealed_read(root/'prepared.json')
    arms = defaultdict(dict)
    for episode in plan['episodes']:
        if episode['policyName'] in (primary, fallback):
            for line in (root/'episodes'/episode['id']/'decisions.jsonl').read_text().splitlines():
                row = json.loads(line)
                arms[(episode['seed'], episode['repeat'])].setdefault(episode['policyName'], {})[row['requestId']] = row
    def tokens(row):
        token = row['tokens'] or {}
        return token.get('value') if token.get('value') is not None else token.get('knownPartial') or 0
    rows = []
    for key, pair in sorted(arms.items()):
        if primary not in pair or fallback not in pair:
            continue
        for request, first in pair[primary].items():
            attempts = [first] + ([pair[fallback][request]] if first['status'] != 'success' else [])
            rows.append({'seed': key[0], 'requestId': request, 'status': attempts[-1]['status'],
                         'fallback': len(attempts) > 1, 'tokensLowerBound': sum(tokens(a) for a in attempts),
                         'durationMs': sum(a['durationMs'] or 0 for a in attempts)})
    if not rows:
        raise ValueError('no paired episodes for the requested arms')
    durations = sorted(r['durationMs'] for r in rows)
    return {'kind': 'counterfactual-cascade', 'provenance': 'derived', 'heldOutDebug': True,
            'primary': primary, 'fallback': fallback, 'requests': len(rows),
            'failures': sum(r['status'] != 'success' for r in rows),
            'fallbacks': sum(r['fallback'] for r in rows),
            'tokensLowerBoundPerRequest': mean(r['tokensLowerBound'] for r in rows),
            'meanLatencyMs': mean(durations),
            'p95LatencyMs': durations[max(0, -(-95*len(durations)//100)-1)]}
