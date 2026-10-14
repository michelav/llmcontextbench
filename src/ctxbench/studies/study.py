"""Prepare held-out episodes bound to exactly one frozen baseline."""
from collections import defaultdict
from pathlib import Path

from ctxbench.adapters.repoqa.study import digest, ordered_workload
from ctxbench.adaptive.recovery import sealed_read, sealed_write, episode_lock
from .baseline import file_hash, prepared_path, verify, VERSION
from .models import Study


def _verify_inputs(plan, allow_source_drift=False):
    """Strict by default; read-only callers may tolerate measurement-source drift only."""
    if not allow_source_drift:
        verify(plan)
        return []
    from ctxbench.adapters.repoqa.study import tree_hash
    from .baseline import measurement_sources
    if plan['schemaVersion'] != VERSION:
        raise ValueError('unsupported study manifest version')
    if file_hash(plan['experimentPath']) != plan['experimentHash']:
        raise ValueError('experiment fingerprint mismatch')
    if tree_hash(Path(plan['datasetRoot'])) != plan['datasetHash']:
        raise ValueError('dataset fingerprint mismatch')
    current, recorded = measurement_sources(), plan['sources']
    drift = sorted(name for name in set(current['files']) | set(recorded['files'])
                   if current['files'].get(name) != recorded['files'].get(name))
    drift += [key for key in ('runtime', 'definitionSchema') if current[key] != recorded[key]]
    return drift


def verify_frozen(frozen, path, *, allow_source_drift=False):
    if frozen['schemaVersion'] != VERSION or frozen['kind'] != 'frozen-baseline':
        raise ValueError('unsupported frozen baseline')
    plan = frozen['plan']
    if frozen['preparedDigest'] != digest(plan):
        raise ValueError('baseline plan digest mismatch')
    _verify_inputs(plan, allow_source_drift)
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
    for delays in definition.scenarios.values():
        for delay in delays:
            if delay.configuration not in selected:
                raise ValueError('delay references an unselected configuration')
            if delay.scope == 'tool-call' and parent['manifest']['configurations'][delay.configuration]['strategy'] != 'local_mcp':
                raise ValueError('tool-call delay requires local_mcp')
    index = parent['index']
    lengths = {len(ordered_workload(index, parent['split']['heldOut'], seed)) for seed in definition.seeds}
    if len(lengths) != 1:
        raise ValueError('unequal study workloads')
    length = lengths.pop()
    if any(delay.lastRequest > length for delays in definition.scenarios.values() for delay in delays):
        raise ValueError('delay range exceeds workload')
    phases = {}
    for scenario, delays in definition.scenarios.items():
        boundaries = sorted({1, length+1, *(d.firstRequest for d in delays),
                             *(d.lastRequest+1 for d in delays)})
        phases[scenario] = [{'firstRequest': start, 'lastRequest': end-1}
                            for start, end in zip(boundaries, boundaries[1:])]
    # Episode identity covers every input that changes behaviour, so IDs never
    # collide across studies that reuse policy names and seeds.
    study_identity = {'baselineDigest': file_hash(baseline_path), 'configurations': selected,
                      'latencyLimitMs': definition.latencyLimitMs, 'tokenBudget': definition.tokenBudget,
                      'minimumCalibrationPassRate': definition.minimumCalibrationPassRate}
    episodes = []
    for seed in definition.seeds:
        workload = [r['instanceId'] for r in ordered_workload(index, parent['split']['heldOut'], seed)]
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
        held_instances = [r['instanceId'] for r in ordered_workload(index, parent['split']['heldOut'], definition.seeds[0])]
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


def verify_study(plan, *, allow_source_drift=False):
    """Return drifted measurement sources; empty unless drift is explicitly allowed."""
    if plan['kind'] != 'study':
        raise ValueError('expected prepared study')
    drift = _verify_inputs(plan, allow_source_drift)
    path = Path(plan['baselinePath'])
    if file_hash(path) != plan['baselineDigest']:
        raise ValueError('frozen baseline digest mismatch')
    verify_frozen(sealed_read(path), path, allow_source_drift=allow_source_drift)
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


def status(path, *, allow_source_drift=False):
    from ctxbench.adaptive.study_runner import load_packets
    path = prepared_path(path)
    plan = sealed_read(path)
    drift = verify_study(plan, allow_source_drift=allow_source_drift)
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


def analyze(path, *, bootstrap_replicates=1000, bootstrap_seed=42, allow_source_drift=False):
    """Paired descriptive analysis. Bootstrap units are targets within language."""
    import json
    import random
    from collections import defaultdict
    from statistics import mean
    from ctxbench.adaptive.study_runner import load_packets
    from ctxbench.adaptive.recovery import write
    path = prepared_path(path)
    plan = sealed_read(path)
    drift = verify_study(plan, allow_source_drift=allow_source_drift)
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
                'passed': outcome.get('passed') if isinstance(outcome,dict) else None,
                'probe': packet['selection']['probe'], 'failures': packet['observation']['failures'] if packet['observation'] else []}
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
            'passRate':mean(quality) if quality else None, 'evaluationCoverage':len(quality),
            'probes':sum(r['probe'] for r in request_rows.values()),
            'budgetOvershoot':max(0,sum(tokens)-plan['definition']['tokenBudget']) if tokens and plan['definition'].get('tokenBudget') else None})
        summaries.append(row)
        key = (e['policyName'],e['scenarioName'],e['seed'],e['repeat'])
        by_arm[key] = request_rows
        complete[key] = len(request_rows) == len(e['workload'])
    comparisons = []
    for left, right in plan['definition']['comparisons']:
        for scenario in plan['definition']['scenarios']:
            units = defaultdict(list)
            pairs = 0
            incomplete = False
            for seed in plan['definition']['seeds']:
                for repeat in range(1,plan['definition']['repeats']+1):
                    a, b = (left,scenario,seed,repeat), (right,scenario,seed,repeat)
                    incomplete |= not (complete.get(a) and complete.get(b))
                    for instance in sorted(set(by_arm.get(a,{})) & set(by_arm.get(b,{}))):
                        x, y = by_arm[a][instance], by_arm[b][instance]
                        if x['latencyMs'] is None or y['latencyMs'] is None:
                            continue
                        units[(x['language'],x['target'])].append(x['latencyMs']-y['latencyMs'])
                        pairs += 1
            grouped = defaultdict(list)
            for (language,_target), values in sorted(units.items()):
                grouped[language].append(mean(values))
            mean_difference = mean([mean(values) for values in grouped.values()]) if grouped else None
            interval = None
            if grouped:
                rng = random.Random(bootstrap_seed)
                samples = []
                for _ in range(bootstrap_replicates):
                    samples.append(mean(mean(rng.choices(values,k=len(values))) for values in grouped.values()))
                samples.sort()
                interval = [samples[int(.025*(bootstrap_replicates-1))], samples[int(.975*(bootstrap_replicates-1))]]
            comparisons.append({'left':left,'right':right,'scenario':scenario,'pairedRequests':pairs,
                'targetClusters':sum(len(v) for v in grouped.values()),'incomplete':incomplete,
                'meanLatencyDifferenceMs':mean_difference,'bootstrap95Ms':interval,
                'bootstrapSeed':bootstrap_seed,'bootstrapReplicates':bootstrap_replicates})
    report = {'schemaVersion':VERSION,'plannedEpisodes':len(plan['episodes']),'phases':plan['phases'],
              'summaries':summaries,
              'comparisons':comparisons, 'dependence':'Targets and frozen baseline are shared across arms and seeds.'}
    if drift:
        report['sourceDrift'] = drift
    report['plots'] = _timeline_plots(path.parent, plan, by_arm)
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


def _timeline_plots(root, plan, by_arm):
    """Derived SVG latency timelines; one mean point per planned sequence position."""
    from html import escape
    from statistics import mean
    plots = []
    directory = root / 'analysis'
    directory.mkdir(exist_ok=True)
    palette = ('#1565c0', '#d84315', '#2e7d32', '#6a1b9a', '#00838f')
    for scenario in plan['definition']['scenarios']:
        lines = []
        all_values = []
        for policy in plan['definition']['policies']:
            by_index = defaultdict(list)
            for episode in plan['episodes']:
                if episode['scenarioName'] != scenario or episode['policyName'] != policy:
                    continue
                rows = by_arm.get((policy,scenario,episode['seed'],episode['repeat']), {})
                for index, instance in enumerate(episode['workload'], 1):
                    row = rows.get(instance)
                    if row and row['latencyMs'] is not None:
                        by_index[index].append(row['latencyMs'])
            points = [(index,mean(values)) for index,values in sorted(by_index.items())]
            all_values.extend(value for _, value in points)
            lines.append((policy,points))
        if not all_values:
            continue
        ceiling = max(all_values) or 1
        width,height = 900,360
        count = max(index for _,points in lines for index,_ in points)
        elements = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Latency by request for {escape(scenario)}">',
                    '<rect width="900" height="360" fill="white"/>',
                    '<path d="M50 20 V310 H880" stroke="#555" fill="none"/>']
        for position,(policy,points) in enumerate(lines):
            if not points:
                continue
            color = palette[position%len(palette)]
            segments = ' '.join(f'{"M" if i==0 else "L"}{50+830*(index-1)/max(1,count-1):.2f},{310-270*value/ceiling:.2f}'
                                for i,(index,value) in enumerate(points))
            elements.append(f'<path d="{segments}" stroke="{color}" stroke-width="2" fill="none"/>')
            elements.append(f'<text x="{65+position*160}" y="342" fill="{color}" font-size="12">{escape(policy)}</text>')
        elements.append('</svg>')
        filename = f'latency-{digest(scenario)[:12]}.svg'
        (directory / filename).write_text('\n'.join(elements))
        plots.append(str(Path('analysis') / filename))
    return plots
