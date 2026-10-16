"""Prepare held-out episodes bound to exactly one frozen baseline."""
from collections import defaultdict
from pathlib import Path

from ctxbench.adapters.repoqa.study import digest, ordered_workload
from ctxbench.adaptive.recovery import sealed_read, sealed_write, episode_lock
from .baseline import file_hash, prepared_path, verify, VERSION
from .models import Study


def parse_path_map(entries):
    """`OLD=NEW` relocations of recorded absolute paths, longest prefix first."""
    pairs = []
    for entry in entries or ():
        old, sep, new = str(entry).partition('=')
        if not sep or not Path(old).is_absolute() or not new:
            raise ValueError(f'path map entry must be OLD=NEW with an absolute OLD: {entry}')
        pairs.append((old.rstrip('/'), str(Path(new).resolve())))
    return sorted(pairs, key=lambda pair: -len(pair[0]))


def local_path(recorded, path_map=()):
    """Where a recorded absolute path lives now. Read-only: the sealed plan is never rewritten."""
    text = str(recorded)
    for old, new in path_map:
        if text == old or text.startswith(old + '/'):
            return Path(new + text[len(old):])
    return Path(text)


def _verify_inputs(plan, allow_source_drift=False, path_map=()):
    """Strict by default; read-only callers may tolerate measurement-source drift only."""
    if not allow_source_drift and not path_map:
        verify(plan)
        return []
    from ctxbench.adapters.repoqa.study import tree_hash
    from .baseline import measurement_sources
    if plan['schemaVersion'] != VERSION:
        raise ValueError('unsupported study manifest version')
    if file_hash(local_path(plan['experimentPath'], path_map)) != plan['experimentHash']:
        raise ValueError('experiment fingerprint mismatch')
    if tree_hash(local_path(plan['datasetRoot'], path_map)) != plan['datasetHash']:
        raise ValueError('dataset fingerprint mismatch')
    current, recorded = measurement_sources(), plan['sources']
    drift = sorted(name for name in set(current['files']) | set(recorded['files'])
                   if current['files'].get(name) != recorded['files'].get(name))
    drift += [key for key in ('runtime', 'definitionSchema') if current[key] != recorded[key]]
    if drift and not allow_source_drift:
        raise ValueError('measurement source fingerprint mismatch')
    return drift


def verify_frozen(frozen, path, *, allow_source_drift=False, path_map=()):
    if frozen['schemaVersion'] != VERSION or frozen['kind'] != 'frozen-baseline':
        raise ValueError('unsupported frozen baseline')
    plan = frozen['plan']
    if frozen['preparedDigest'] != digest(plan):
        raise ValueError('baseline plan digest mismatch')
    _verify_inputs(plan, allow_source_drift, path_map)
    for relative, expected in frozen['artifacts'].items():
        artifact = path.parent / relative
        if not artifact.is_file() or file_hash(artifact) != expected:
            raise ValueError(f'frozen baseline artifact mismatch: {relative}')
    return plan


def prepare(*, definition, output):
    definition_path = Path(definition).resolve()
    definition = Study.model_validate_json(definition_path.read_text())
    baseline_path = (definition_path.parent / definition.baseline).resolve()
    frozen = sealed_read(baseline_path)
    parent = verify_frozen(frozen, baseline_path)
    selected = definition.configurations or list(parent['configurations'])
    if any(cid not in parent['configurations'] for cid in selected):
        raise ValueError('unknown configuration subset')
    if any(p.type == 'fixed' and p.configuration not in selected for p in definition.policies.values()):
        raise ValueError('fixed policy references an unselected configuration')
    if any(p.type == 'cascade' and any(cid not in selected for cid in (p.primary, *p.fallbacks))
           for p in definition.policies.values()):
        raise ValueError('cascade policy references an unselected configuration')
    for delays in definition.scenarios.values():
        for delay in delays:
            if delay.kind == 'token-quota':
                continue
            if delay.configuration not in selected:
                raise ValueError(f'{delay.kind} references an unselected configuration')
            strategy = parent['manifest']['configurations'][delay.configuration]['strategy']
            if delay.kind == 'delay' and delay.scope == 'tool-call' and strategy != 'local_mcp':
                raise ValueError('tool-call delay requires local_mcp')
            if delay.kind == 'fault' and strategy != 'local_mcp':
                raise ValueError('fault injection requires local_mcp')
    for policy in definition.policies.values():
        if policy.type == 'schedule':
            mappings = [policy.default, *(phase.configurationBySize for phase in policy.phases)]
            if any(cid not in selected for mapping in mappings for cid in mapping.values()):
                raise ValueError('schedule policy references an unselected configuration')
    index = parent['index']
    # Pilots may use a subset of held-out targets; calibration targets are never allowed.
    targets = definition.targets or parent['split']['heldOut']
    if any(target not in parent['split']['heldOut'] for target in targets):
        raise ValueError('study targets must be held-out targets of the baseline')
    lengths = {len(ordered_workload(index, targets, seed)) for seed in definition.seeds}
    if len(lengths) != 1:
        raise ValueError('unequal study workloads')
    length = lengths.pop()
    if any(delay.lastRequest > length for delays in definition.scenarios.values() for delay in delays):
        raise ValueError('delay range exceeds workload')
    if any(phase.lastRequest > length for policy in definition.policies.values() if policy.type == 'schedule'
           for phase in policy.phases):
        raise ValueError('schedule phase exceeds workload')
    phases = {}
    for scenario, delays in definition.scenarios.items():
        boundaries = sorted({1, length+1, *(d.firstRequest for d in delays),
                             *(d.lastRequest+1 for d in delays)})
        phases[scenario] = [{'firstRequest': start, 'lastRequest': end-1}
                            for start, end in zip(boundaries, boundaries[1:])]
    # Episode identity covers every input that changes behaviour, so IDs never
    # collide across studies that reuse policy names and seeds.
    study_identity = {'baselineDigest': file_hash(baseline_path), 'configurations': selected, 'targets': targets,
                      'latencyLimitMs': definition.latencyLimitMs, 'tokenBudget': definition.tokenBudget,
                      'minimumCalibrationPassRate': definition.minimumCalibrationPassRate}
    episodes = []
    for seed in definition.seeds:
        workload = [r['instanceId'] for r in ordered_workload(index, targets, seed)]
        for repeat in range(1, definition.repeats+1):
            for scenario, delays in definition.scenarios.items():
                for policy, config in definition.policies.items():
                    identity = {'policyName': policy, 'scenarioName': scenario, 'seed': seed, 'repeat': repeat}
                    behaviour = {**identity, 'policy': config.model_dump(), 'workload': workload,
                                 'scenario': [d.model_dump() for d in delays], 'study': study_identity}
                    episodes.append({**identity, 'id': digest(behaviour)[:24], 'workload': workload,
                                     'policy': config.model_dump(), 'scenario': [d.model_dump() for d in delays]})
    estimates = {cid: frozen['estimates'][cid] for cid in selected}
    quality = {cid: frozen['quality'][cid] for cid in selected}
    if definition.minimumCalibrationPassRate is not None and not any(
        q['passRate'] is not None and q['passRate'] >= definition.minimumCalibrationPassRate for q in quality.values()
    ):
        raise ValueError('no configuration meets the calibration quality floor')
    cheapest = None
    if any(p.type == 'budget' for p in definition.policies.values()):
        fixed = {p.configuration for p in definition.policies.values() if p.type == 'fixed'}
        if fixed != set(selected):
            raise ValueError('budget study requires a fixed policy for every selected configuration')
        held_instances = [r['instanceId'] for r in ordered_workload(index, targets, definition.seeds[0])]
        sizes = [parent['requests'][instance]['sizeBin'] for instance in held_instances]
        forecast = {}
        for cid in selected:
            rate = quality[cid]['passRate']
            if definition.minimumCalibrationPassRate is not None and (rate is None or rate < definition.minimumCalibrationPassRate):
                continue
            candidate_rows = [parent['requests'][instance]['candidates'][cid] for instance in held_instances]
            if any(not row['executable'] or
                   row['context_fit']['input_tokens'] + row['context_fit']['output_reservation'] > row['context_fit']['context_limit']
                   for row in candidate_rows):
                continue
            values = [estimates[cid][size]['tokens'] for size in sizes]
            if all(v is not None for v in values):
                forecast[cid] = sum(values)
        if not forecast:
            raise ValueError('budget study requires calibration token estimates for at least one qualified configuration')
        cheapest = min(forecast, key=lambda cid: (forecast[cid], selected.index(cid)))
    requests = {}
    for instance, request in parent['requests'].items():
        requests[instance] = {**request,
            'candidates': {cid: request['candidates'][cid] for cid in selected},
            'trials': {cid: request['trials'][cid] for cid in selected}}
    manifest = dict(parent['manifest'])
    manifest['configurations'] = {cid: manifest['configurations'][cid] for cid in selected}
    plan = {'schemaVersion': VERSION, 'kind': 'study', 'definition': definition.model_dump(),
        'baselinePath': str(baseline_path), 'baselineDigest': file_hash(baseline_path),
        'experimentPath': parent['experimentPath'], 'experimentHash': parent['experimentHash'],
        'datasetRoot': parent['datasetRoot'], 'datasetHash': parent['datasetHash'],
        'sources': parent['sources'], 'split': parent['split'], 'index': index,
        'configurations': selected, 'requests': requests, 'estimates': estimates, 'quality': quality,
        'tokenQuantiles': _token_quantiles(frozen, selected),
        'latencyQuantiles': _latency_quantiles(frozen, selected),
        'calibrationSizeMix': _calibration_size_mix(parent),
        'episodes': episodes, 'manifest': manifest, 'budget': parent['budget'], 'phases': phases,
        'resolved': {'protocolVersion': 3, 'estimator': 'all-observations-v1',
                     'tieOrder': selected, 'failureMonitoring': 'execution-only',
                     'probeRotation': 'eligible-alternatives-v1',
                     'cheapestQualifiedFixed': cheapest}}
    output = Path(output).resolve()
    with episode_lock(output):
        if any(p.name != '.episode.lock' for p in output.iterdir()):
            raise ValueError('prepare requires fresh output')
        sealed_write(output / 'prepared.json', plan)
    return {'prepared': str(output / 'prepared.json'), 'episodes': len(episodes), 'baselineDigest': plan['baselineDigest']}


def verify_study(plan, *, allow_source_drift=False, path_map=()):
    """Return drifted measurement sources; empty unless drift is explicitly allowed."""
    if plan['kind'] != 'study':
        raise ValueError('expected prepared study')
    drift = _verify_inputs(plan, allow_source_drift, path_map)
    path = local_path(plan['baselinePath'], path_map)
    if file_hash(path) != plan['baselineDigest']:
        raise ValueError('frozen baseline digest mismatch')
    verify_frozen(sealed_read(path), path, allow_source_drift=allow_source_drift, path_map=path_map)
    return drift


def episode(*, prepared, policy, scenario, seed, repeat, resume=False, retry_uncertain=False,
            execution=None, checkpoint=lambda *_: None,
            monotonic=None, sleeper=None):
    from ctxbench.adaptive.study_runner import run
    path = prepared_path(prepared)
    plan = sealed_read(path)
    verify_study(plan)
    matches = [e for e in plan['episodes'] if (e['policyName'], e['scenarioName'], e['seed'], e['repeat']) ==
               (policy, scenario, seed, repeat)]
    if len(matches) != 1:
        raise ValueError('episode is not in prepared matrix')
    kwargs = {'resume': resume, 'retry_uncertain': retry_uncertain,
              'execution': execution, 'checkpoint': checkpoint}
    if monotonic: kwargs['monotonic'] = monotonic
    if sleeper: kwargs['sleeper'] = sleeper
    packets = run(plan, matches[0], path.parent / 'episodes' / matches[0]['id'], **kwargs)
    return {'episode': matches[0]['id'], 'completedRequests': len(packets)}


def status(path, *, allow_source_drift=False, path_map=None):
    from ctxbench.adaptive.study_runner import load_packets
    path = prepared_path(path)
    plan = sealed_read(path)
    drift = verify_study(plan, allow_source_drift=allow_source_drift, path_map=parse_path_map(path_map))
    matrix = []
    for e in plan['episodes']:
        packets = load_packets(path.parent / 'episodes' / e['id'])
        matrix.append({key: e[key] for key in ('id','policyName','scenarioName','seed','repeat')} |
                      {'planned': len(e['workload']), 'completed': sum(p['state']=='completed' for p in packets),
                       'failed': sum(p['state']=='completed' and p['observation'] is not None and p['observation']['status']!='success' for p in packets),
                       'unserved': sum(p['state']=='completed' and p['observation'] is None for p in packets)})
    report = {'schemaVersion': VERSION, 'matrix': matrix}
    if drift:
        report['sourceDrift'] = drift
    return report


def analyze(path, *, bootstrap_replicates=1000, bootstrap_seed=42, allow_source_drift=False, path_map=None):
    """Paired descriptive analysis. Bootstrap units are targets within language."""
    import json
    import random
    from collections import defaultdict
    from statistics import mean
    from ctxbench.adaptive.study_runner import load_packets
    from ctxbench.adaptive.recovery import write
    path = prepared_path(path)
    plan = sealed_read(path)
    drift = verify_study(plan, allow_source_drift=allow_source_drift, path_map=parse_path_map(path_map))
    if type(bootstrap_replicates) is not int or bootstrap_replicates < 1:
        raise ValueError('bootstrap_replicates must be a positive integer')
    summaries, by_arm, complete = [], {}, {}
    for e in plan['episodes']:
        root = path.parent / 'episodes' / e['id']
        packets = load_packets(root)
        evaluations = {row['trialId']: row for row in baseline_rows(root / 'evals.jsonl')}
        request_rows = {}
        for packet in packets:
            if packet['state'] != 'completed':
                continue
            request = plan['requests'][packet['instanceId']]
            result = packet['result']
            evaluation = evaluations.get(result['trialId']) if result else None
            outcome = evaluation.get('outcome') if evaluation else None
            request_rows[packet['instanceId']] = {'target':request['target'], 'language':request['language'],
                'status': result['status'] if result else 'unserved',
                'latencyMs': packet['observation']['durationMs'] if packet['observation'] else None,
                'tokens': packet['observation']['tokens']['value'] if packet['observation'] else None,
                'tokenLowerBound': (packet['observation']['tokens']['value']
                                    if packet['observation']['tokens']['value'] is not None
                                    else packet['observation']['tokens']['knownPartial'] or 0)
                                   if packet['observation'] else None,
                'attempts': packet.get('attempts', [None] if packet['observation'] else []),
                'passed': outcome.get('passed') if isinstance(outcome,dict) else None,
                'probe': packet['selection']['probe'], 'failures': packet['observation']['failures'] if packet['observation'] else [],
                'sequenceIndex': packet['sequenceIndex'], 'configuration': packet['selection']['configuration'],
                'finalConfiguration': packet['observation']['configuration'] if packet['observation'] else None,
                'controllerMs': packet['decision'].get('controllerMs')}
        durations = [r['latencyMs'] for r in request_rows.values() if r['latencyMs'] is not None]
        tokens = [r['tokens'] for r in request_rows.values() if r['tokens'] is not None]
        quality = [r['passed'] for r in request_rows.values() if type(r['passed']) is bool]
        limit = plan['definition'].get('latencyLimitMs')
        row = {k:e[k] for k in ('id','policyName','scenarioName','seed','repeat')}
        row.update({'planned':len(e['workload']), 'completed':len(request_rows),
            'success':sum(r['status']=='success' for r in request_rows.values()),
            'failure':sum(r['status'] not in ('success','unserved') for r in request_rows.values()),
            'unserved':sum(r['status']=='unserved' for r in request_rows.values()),
            'meanLatencyMs':mean(durations) if durations else None,
            'deadlineMisses':sum(x>limit for x in durations) if limit is not None else None,
            'knownTokens':sum(tokens) if tokens else None, 'tokenCoverage':len(tokens),
            # Unknown totals contribute their known partial usage: a derived lower bound over all executions.
            'tokensLowerBound':sum(r['tokenLowerBound'] for r in request_rows.values() if r['tokenLowerBound'] is not None),
            'fallbacks':sum(len(r['attempts']) > 1 for r in request_rows.values()),
            'wastedTokensLowerBound':sum(sum(a['observation']['tokens']['value'] if a['observation']['tokens']['value'] is not None
                                             else a['observation']['tokens']['knownPartial'] or 0
                                             for a in r['attempts'][:-1]) for r in request_rows.values()),
            'passRate':mean(quality) if quality else None, 'evaluationCoverage':len(quality),
            'probes':sum(r['probe'] for r in request_rows.values()),
            'budgetOvershoot':max(0,sum(tokens)-plan['definition']['tokenBudget']) if tokens and plan['definition'].get('tokenBudget') else None})
        row.update(_episode_details(list(request_rows.values()), len(e['workload']), limit,
                                    plan['phases'][e['scenarioName']], e['scenario']))
        summaries.append(row)
        key = (e['policyName'],e['scenarioName'],e['seed'],e['repeat'])
        by_arm[key] = request_rows
        complete[key] = len(request_rows) == len(e['workload'])
    limit = plan['definition'].get('latencyLimitMs')
    paired_metrics = {
        'latencyMs': lambda r: r['latencyMs'],
        'deadlineMiss': lambda r: None if limit is None or r['latencyMs'] is None else float(r['latencyMs'] > limit),
        'tokensLowerBound': lambda r: r['tokenLowerBound'],
        'failure': lambda r: float(r['status'] != 'success'),
        'passed': lambda r: float(r['passed'] is True),
    }
    comparisons = []
    for left, right in plan['definition']['comparisons']:
        for scenario in plan['definition']['scenarios']:
            units = {name: defaultdict(list) for name in paired_metrics}
            pairs = 0
            incomplete = False
            for seed in plan['definition']['seeds']:
                for repeat in range(1,plan['definition']['repeats']+1):
                    a, b = (left,scenario,seed,repeat), (right,scenario,seed,repeat)
                    incomplete |= not (complete.get(a) and complete.get(b))
                    for instance in sorted(set(by_arm.get(a,{})) & set(by_arm.get(b,{}))):
                        x, y = by_arm[a][instance], by_arm[b][instance]
                        for name, metric in paired_metrics.items():
                            if metric(x) is not None and metric(y) is not None:
                                units[name][(x['language'],x['target'])].append(metric(x)-metric(y))
                        if x['latencyMs'] is not None and y['latencyMs'] is not None:
                            pairs += 1
            metrics = {name: _cluster_bootstrap(values, bootstrap_seed, bootstrap_replicates)
                       for name, values in units.items()}
            latency = metrics['latencyMs']
            comparisons.append({'left':left,'right':right,'scenario':scenario,'pairedRequests':pairs,
                'targetClusters':latency['targetClusters'],'incomplete':incomplete,
                'meanLatencyDifferenceMs':latency['meanDifference'],'bootstrap95Ms':latency['bootstrap95'],
                'bootstrapSeed':bootstrap_seed,'bootstrapReplicates':bootstrap_replicates,
                'metrics': metrics})
    report = {'schemaVersion':VERSION,'plannedEpisodes':len(plan['episodes']),'phases':plan['phases'],
              'summaries':summaries, 'arms': _arm_aggregates(summaries),
              'comparisons':comparisons, 'dependence':'Targets and frozen baseline are shared across arms and seeds.'}
    if drift:
        report['sourceDrift'] = drift
    report['plots'] = _timeline_plots(path.parent, plan, by_arm) + _tradeoff_plots(path.parent, plan, report['arms'])
    write(path.parent / 'analysis.json', report)
    return report


def baseline_rows(path):
    from .baseline import rows
    return rows(path)


def _token_quantiles(frozen, configurations):
    """Calibration token p95/max per configuration and bin (nearest rank; successes with known usage)."""
    values = defaultdict(list)
    for row in frozen.get('observations', []):
        token = row['tokens']['value'] if isinstance(row.get('tokens'), dict) else row.get('tokens')
        if row.get('status') == 'success' and token is not None:
            values[(row['configuration'], row['sizeBin'])].append(token)
    result = {}
    for cid in configurations:
        result[cid] = {}
        for (config, size), sample in values.items():
            if config == cid:
                sample = sorted(sample)
                result[cid][size] = {'p95': sample[max(0, -(-95*len(sample)//100)-1)], 'max': sample[-1],
                                     'observations': len(sample), 'provenance': 'derived'}
    return result


LATENCY_QUANTILES = (0.5, 0.75, 0.9, 0.95)


def _latency_quantiles(frozen, configurations):
    """Calibration latency quantiles per configuration and bin (nearest rank; successes only)."""
    values = defaultdict(list)
    for row in frozen.get('observations', []):
        if row.get('status') == 'success' and row.get('durationMs') is not None:
            values[(row['configuration'], row['sizeBin'])].append(row['durationMs'])
    result = {cid: {} for cid in configurations}
    for (cid, size), sample in values.items():
        if cid in result:
            sample = sorted(sample)
            result[cid][size] = {str(q): sample[max(0, -(-int(q*100)*len(sample)//100)-1)] for q in LATENCY_QUANTILES}
            result[cid][size]['observations'] = len(sample)
    return result


def _calibration_size_mix(parent):
    counts = defaultdict(int)
    calibration = set(parent['split']['calibration'])
    for request in parent['requests'].values():
        if request['target'] in calibration:
            counts[request['sizeBin']] += 1
    total = sum(counts.values())
    return {size: count/total for size, count in sorted(counts.items())} if total else {}


def _cluster_bootstrap(units, seed, replicates):
    """Mean paired difference over target clusters within language, with a percentile bootstrap."""
    import random
    from statistics import mean
    grouped = defaultdict(list)
    for (language, _target), values in sorted(units.items()):
        grouped[language].append(mean(values))
    if not grouped:
        return {'meanDifference': None, 'bootstrap95': None, 'targetClusters': 0}
    rng = random.Random(seed)
    samples = sorted(mean(mean(rng.choices(values, k=len(values))) for values in grouped.values())
                     for _ in range(replicates))
    return {'meanDifference': mean(mean(values) for values in grouped.values()),
            'bootstrap95': [samples[int(.025*(replicates-1))], samples[int(.975*(replicates-1))]],
            'targetClusters': sum(len(v) for v in grouped.values())}


def _quantile(values, probability):
    ordered = sorted(values)
    return ordered[max(0, -(-int(probability*100)*len(ordered)//100)-1)] if ordered else None


def _episode_details(rows, planned, limit, phases, effects):
    """Derived per-episode metrics: all-request quality, switching, probe cost, overhead, phases, lags."""
    from statistics import mean
    from .replay import _lags
    rows = sorted(rows, key=lambda r: r['sequenceIndex'])
    routed = [r['configuration'] for r in rows if not r['probe'] and r['configuration']]
    probes = [r for r in rows if r['probe']]
    overhead = [r['controllerMs'] for r in rows if r['controllerMs'] is not None]
    def missed(r):
        return limit is not None and r['latencyMs'] is not None and r['latencyMs'] > limit
    phase_rows = []
    for phase in phases:
        inside = [r for r in rows if phase['firstRequest'] <= r['sequenceIndex'] <= phase['lastRequest']]
        latencies = [r['latencyMs'] for r in inside if r['latencyMs'] is not None]
        phase_rows.append({**phase, 'completed': len(inside),
            'deadlineMisses': sum(missed(r) for r in inside) if limit is not None else None,
            'meanLatencyMs': mean(latencies) if latencies else None,
            'tokensLowerBound': sum(r['tokenLowerBound'] or 0 for r in inside),
            'failures': sum(r['status'] not in ('success', 'unserved') for r in inside),
            'passed': sum(r['passed'] is True for r in inside)})
    return {'passRateAllRequests': sum(r['passed'] is True for r in rows)/planned if planned else None,
            'switches': sum(a != b for a, b in zip(routed, routed[1:])),
            'probeTokensLowerBound': sum(r['tokenLowerBound'] or 0 for r in probes),
            'probeDeadlineMisses': sum(missed(r) for r in probes) if limit is not None else None,
            'controllerMsP50': _quantile(overhead, .5), 'controllerMsP95': _quantile(overhead, .95),
            'phaseSummaries': phase_rows, 'lags': _lags(rows, effects)}


ARM_FIELDS = ('completed', 'success', 'failure', 'unserved', 'meanLatencyMs', 'deadlineMisses', 'knownTokens',
              'tokensLowerBound', 'passRate', 'passRateAllRequests', 'probes', 'fallbacks', 'switches',
              'probeTokensLowerBound', 'controllerMsP95')


def _arm_aggregates(summaries):
    """Per policy and scenario: mean, minimum and maximum over completed episodes (seeds × repeats)."""
    from statistics import mean
    groups = defaultdict(list)
    for row in summaries:
        if row['completed']:
            groups[(row['policyName'], row['scenarioName'])].append(row)
    arms = []
    for (policy, scenario), rows in groups.items():
        arm = {'policyName': policy, 'scenarioName': scenario, 'episodes': len(rows)}
        for field in ARM_FIELDS:
            values = [r[field] for r in rows if r.get(field) is not None]
            arm[field] = {'mean': mean(values), 'min': min(values), 'max': max(values)} if values else None
        lags = [lag for r in rows for lag in r['lags']]
        for key in ('reactionLag', 'recoveryLag'):
            known = [lag[key] for lag in lags if lag[key] is not None]
            # Lags that never happened (no switch / no return) are counted, not averaged.
            arm[key] = {'mean': mean(known) if known else None, 'observed': len(known),
                        'episodes': len(lags)} if lags else None
        arms.append(arm)
    return arms


# Reference palette (dataviz skill, light surface); categorical slots in fixed order.
SURFACE, INK, INK_2, MUTED, GRID, AXIS = '#fcfcfb', '#0b0b0b', '#52514e', '#898781', '#e1e0d9', '#c3c2b7'
SERIES = ('#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948')
FONT = 'font-family="system-ui, sans-serif"'


def _text(x, y, label, size=11, fill=INK_2, anchor='start', weight='normal'):
    from html import escape
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{escape(str(label))}</text>')


def _nice_ceiling(value):
    """Smallest round axis maximum (quarter ticks stay round) at or above value."""
    for magnitude in (0.01, 0.1, 1, 10, 100, 1000, 10000, 100000, 1000000):
        for step in (1, 2, 4, 6, 8):
            if step*magnitude >= value:
                return step*magnitude
    return value


def _timeline_plots(root, plan, by_arm):
    """Small multiples per scenario: mean latency per request position, limit, disturbance bands and routing."""
    from statistics import mean
    from collections import Counter
    plots = []
    directory = root / 'analysis'
    directory.mkdir(exist_ok=True)
    limit = plan['definition'].get('latencyLimitMs')
    colors = {cid: SERIES[i % len(SERIES)] for i, cid in enumerate(plan['configurations'])}
    for scenario in plan['definition']['scenarios']:
        panels = []
        for policy in plan['definition']['policies']:
            by_index, routes = defaultdict(list), defaultdict(Counter)
            for episode in plan['episodes']:
                if episode['scenarioName'] != scenario or episode['policyName'] != policy:
                    continue
                rows = by_arm.get((policy, scenario, episode['seed'], episode['repeat']), {})
                for index, instance in enumerate(episode['workload'], 1):
                    row = rows.get(instance)
                    if row and row['latencyMs'] is not None:
                        by_index[index].append(row['latencyMs']/1000)
                    if row and row.get('finalConfiguration'):
                        routes[index][row['finalConfiguration']] += 1
            panels.append((policy, [(i, mean(v)) for i, v in sorted(by_index.items())],
                           {i: c.most_common(1)[0][0] for i, c in routes.items()}))
        values = [v for _, points, _ in panels for _, v in points]
        if not values:
            continue
        count = max(len(e['workload']) for e in plan['episodes'])
        ceiling = _nice_ceiling(max(values + ([limit/1000] if limit else [])) * 1.05)
        left, right, top, panel_h, strip_h, gap = 64, 24, 46, 96, 8, 30
        width = 900
        plot_w = width-left-right
        height = top + len(panels)*(panel_h+strip_h+gap) + 64
        x_of = lambda i: left + plot_w*(i-1)/max(1, count-1)
        effects = next((e['scenario'] for e in plan['episodes'] if e['scenarioName'] == scenario), [])
        bands = [(e['firstRequest'], e['lastRequest'],
                  f"{e.get('kind', 'delay')} {e.get('configuration', 'all')}") for e in effects]
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
               f'aria-label="Mean latency per request position for {scenario}">',
               f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>',
               _text(left, 22, f'{scenario}: mean end-to-end latency per request position', 14, INK, weight='600'),
               _text(left, 38, 'Latency in seconds, mean over seeds; the strip under each panel shows the '
                     'configuration most often executed at each position.', 11)]
        for row_index, (policy, points, routes) in enumerate(panels):
            y0 = top + row_index*(panel_h+strip_h+gap) + 14
            y_of = lambda v: y0 + panel_h - panel_h*v/ceiling
            out.append(_text(left, y0-4, policy, 12, INK, weight='600'))
            for first, last, label in bands:
                x1, x2 = x_of(first) - plot_w/(2*max(1, count-1)), x_of(last) + plot_w/(2*max(1, count-1))
                out.append(f'<rect x="{x1:.1f}" y="{y0}" width="{x2-x1:.1f}" height="{panel_h}" fill="{GRID}" opacity="0.6"/>')
                if row_index == 0:
                    out.append(_text((x1+x2)/2, y0+12, label, 10, MUTED, 'middle'))
            for tick in (0, ceiling/2, ceiling):
                y = y_of(tick)
                out.append(f'<line x1="{left}" x2="{left+plot_w}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
                out.append(_text(left-6, y+4, f'{tick:g}', 10, MUTED, 'end'))
            if limit:
                y = y_of(limit/1000)
                out.append(f'<line x1="{left}" x2="{left+plot_w}" y1="{y:.1f}" y2="{y:.1f}" stroke="{INK_2}" '
                           f'stroke-width="1" stroke-dasharray="4 3"/>')
                out.append(_text(left+plot_w, y-4, f'limit {limit/1000:g} s', 10, INK_2, 'end'))
            if points:
                path = ' '.join(f'{"M" if k == 0 else "L"}{x_of(i):.1f},{y_of(v):.1f}' for k, (i, v) in enumerate(points))
                out.append(f'<path d="{path}" stroke="{INK}" stroke-width="2" fill="none" stroke-linejoin="round"/>')
            strip_y = y0 + panel_h + 3
            cell = plot_w/max(1, count)
            for i, cid in routes.items():
                out.append(f'<rect x="{x_of(i)-cell/2:.1f}" y="{strip_y}" width="{max(1, cell-1):.1f}" '
                           f'height="{strip_h}" fill="{colors.get(cid, MUTED)}"/>')
        axis_y = top + len(panels)*(panel_h+strip_h+gap) - gap + 30
        for tick in range(0, count+1, 10 if count > 30 else 5):
            if tick:
                out.append(_text(x_of(tick), axis_y, tick, 10, MUTED, 'middle'))
        out.append(_text(left+plot_w/2, axis_y+16, 'Request position in episode', 11, INK_2, 'middle'))
        legend_x = left
        for cid, color in colors.items():
            out.append(f'<rect x="{legend_x}" y="{axis_y+26}" width="10" height="10" rx="2" fill="{color}"/>')
            out.append(_text(legend_x+14, axis_y+35, cid, 10, INK_2))
            legend_x += 20 + 6.2*len(cid)
        out.append('</svg>')
        filename = f'latency-{digest(scenario)[:12]}.svg'
        (directory / filename).write_text('\n'.join(out))
        plots.append(str(Path('analysis') / filename))
    return plots


def _tradeoff_plots(root, plan, arms):
    """Per scenario: token lower bound per request against deadline-miss (or failure) rate, one point per policy."""
    plots = []
    limit = plan['definition'].get('latencyLimitMs')
    order = list(plan['definition']['policies'])
    colors = {name: SERIES[i % len(SERIES)] for i, name in enumerate(order)}
    for scenario in plan['definition']['scenarios']:
        points = []
        for arm in arms:
            if arm['scenarioName'] != scenario or not arm['completed'] or not arm['tokensLowerBound']:
                continue
            completed = arm['completed']['mean']
            rate = arm['deadlineMisses'] if limit is not None else arm['failure']
            if rate is None:
                continue
            points.append((arm['policyName'], arm['tokensLowerBound']['mean']/completed/1000,
                           100*rate['mean']/completed, 100*rate['min']/completed, 100*rate['max']/completed))
        if len(points) < 2:
            continue
        width, height, left, right, top, bottom = 640, 420, 64, 150, 76, 56
        plot_w, plot_h = width-left-right, height-top-bottom
        x_max = _nice_ceiling(max(p[1] for p in points)*1.1)
        y_max = _nice_ceiling(max(max(p[4] for p in points)*1.1, 1))
        x_of = lambda v: left + plot_w*v/x_max
        y_of = lambda v: top + plot_h - plot_h*v/y_max
        measure = 'Deadline-miss rate (%)' if limit is not None else 'Failure rate (%)'
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
               f'aria-label="Token cost against {measure.lower()} for {scenario}">',
               f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>',
               _text(left, 22, f'{scenario}: cost against {measure.split(" (")[0].lower()}', 14, INK, weight='600'),
               _text(left, 38, 'Point = mean over episodes; bar = range across seeds. Lower-left is better.', 11)]
        for k in range(5):
            xv, yv = x_max*k/4, y_max*k/4
            out.append(f'<line x1="{left}" x2="{left+plot_w}" y1="{y_of(yv):.1f}" y2="{y_of(yv):.1f}" stroke="{GRID}"/>')
            out.append(_text(left-6, y_of(yv)+4, f'{yv:g}', 10, MUTED, 'end'))
            out.append(_text(x_of(xv), top+plot_h+16, f'{xv:g}', 10, MUTED, 'middle'))
        out.append(f'<line x1="{left}" x2="{left+plot_w}" y1="{top+plot_h}" y2="{top+plot_h}" stroke="{AXIS}"/>')
        out.append(_text(left+plot_w/2, height-14, 'Tokens per request, lower bound (thousands)', 11, INK_2, 'middle'))
        out.append(_text(left-6, top-14, measure, 11, INK_2, 'start'))
        for name, x, y, low, high in points:
            out.append(f'<line x1="{x_of(x):.1f}" x2="{x_of(x):.1f}" y1="{y_of(low):.1f}" y2="{y_of(high):.1f}" '
                       f'stroke="{colors[name]}" stroke-width="2"/>')
            out.append(f'<circle cx="{x_of(x):.1f}" cy="{y_of(y):.1f}" r="5" fill="{colors[name]}" '
                       f'stroke="{SURFACE}" stroke-width="2"/>')
            out.append(_text(x_of(x)+8, y_of(y)-6, name, 10, INK_2))
        for k, (name, *_rest) in enumerate(points):
            ly = top + 14*k
            out.append(f'<rect x="{left+plot_w+20}" y="{ly}" width="10" height="10" rx="2" fill="{colors[name]}"/>')
            out.append(_text(left+plot_w+34, ly+9, name, 10, INK_2))
        out.append('</svg>')
        filename = f'tradeoff-{digest(scenario)[:12]}.svg'
        (root / 'analysis' / filename).write_text('\n'.join(out))
        plots.append(str(Path('analysis') / filename))
    return plots
