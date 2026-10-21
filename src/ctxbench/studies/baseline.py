"""Prepare and freeze reusable RepoQA measurements without contacting providers."""
from collections import defaultdict
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import random
import sys
from statistics import mean

from ctxbench.adapters.repoqa.package import RepoQADatasetAdapter
from ctxbench.adapters.repoqa.study import SIZE_PROFILES, digest, tree_hash, initial_budget, ordered_workload, size_profile
from ctxbench.adapters.repoqa.workload import prepare_request_features
from ctxbench.adaptive.recovery import sealed_read, sealed_write, episode_lock
from ctxbench.benchmark.models import Experiment, DatasetProvenance, TrialSpec
from ctxbench.benchmark.runspec_generator import generate_runspecs
from .models import Baseline, InstanceSplit

VERSION = 3


def measurement_sources():
    """Only code affecting population, tools, execution, timing or evaluation."""
    import subprocess
    root = Path(__file__).resolve().parents[3]
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    paths = [root / name for name in (
        'src/ctxbench/studies/baseline.py',
        'src/ctxbench/adaptive/study_runner.py',
        'src/ctxbench/ai/mcp_result.py',
        'src/ctxbench/benchmark/executor.py',
        'src/ctxbench/benchmark/runtime_adapter.py',
        'src/ctxbench/benchmark/runspec_generator.py',
        'src/ctxbench/adapters/repoqa/provider.py',
        'src/ctxbench/adapters/repoqa/tools.py',
        'src/ctxbench/adapters/repoqa/mcp_server.py',
        'src/ctxbench/adapters/repoqa/package.py',
        'src/ctxbench/adapters/repoqa/evaluation.py',
        'src/ctxbench/adapters/repoqa/study.py',
        'src/ctxbench/adapters/repoqa/workload.py',
        'pyproject.toml', 'uv.lock',
    )]
    paths.extend((root / 'src/ctxbench/ai').rglob('*.py'))
    paths.extend((root / 'tools/repoqa').rglob('*.py'))
    return {'revision': revision, 'definitionSchema': digest(Baseline.model_json_schema()),
            'files': {str(p.relative_to(root)): file_hash(p) for p in sorted(set(paths)) if p.is_file()},
            'runtime': {'python': sys.version.split()[0], 'fastmcp': version('fastmcp')}}


def file_hash(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def prepared_path(path):
    path = Path(path).resolve()
    return path / 'prepared.json' if path.is_dir() else path


def verify(plan):
    if plan['schemaVersion'] != VERSION:
        raise ValueError('unsupported study manifest version')
    current = measurement_sources()
    if any(current[key] != plan['sources'][key] for key in ('files', 'runtime', 'definitionSchema')):
        raise ValueError('measurement source fingerprint mismatch')
    if file_hash(plan['experimentPath']) != plan['experimentHash']:
        raise ValueError('experiment fingerprint mismatch')
    if tree_hash(Path(plan['datasetRoot'])) != plan['datasetHash']:
        raise ValueError('dataset fingerprint mismatch')


def prepare(*, definition, output):
    definition_path = Path(definition).resolve()
    definition = Baseline.model_validate_json(definition_path.read_text())
    experiment_path = (definition_path.parent / definition.experiment).resolve()
    experiment = Experiment.model_validate_json(experiment_path.read_text())
    if experiment.execution.repeats != 1:
        raise ValueError('baseline requires experiment execution.repeats: 1')
    dataset_root = (experiment_path.parent / experiment.dataset.root).resolve()
    adapter = RepoQADatasetAdapter(dataset_root)
    provenance = DatasetProvenance(id=adapter.identity(), version=adapter.version(), materialized_path=str(dataset_root))
    trials = generate_runspecs(experiment, experiment_path.parent, adapter, provenance, experiment_path=experiment_path)
    configurations = list(experiment.factors['configuration'])
    if not trials or len({(t.provider, t.modelId, t.modelName) for t in trials}) != 1:
        raise ValueError('baseline requires exactly one answering model')
    if len({t.taskId for t in trials}) != 1:
        raise ValueError('V1 requires one RepoQA task')
    if any(t.strategy not in ('inline', 'local_function', 'local_mcp', 'remote_mcp') for t in trials):
        raise ValueError('baseline supports inline, local_function, local_mcp and remote_mcp')
    by_instance = defaultdict(dict)
    for trial in trials:
        if trial.configurationId in by_instance[trial.instanceId]:
            raise ValueError('duplicate candidate trial')
        for key in ('max_tokens', 'max_output_tokens'):
            if key in trial.params and trial.params[key] != definition.outputReservation:
                raise ValueError('output reservation differs from configured max tokens')
        if 'context_limit' in trial.params and trial.params['context_limit'] != definition.contextLimit:
            raise ValueError('context limit differs from model params')
        trial.params['max_tokens'] = definition.outputReservation
        by_instance[trial.instanceId][trial.configurationId] = trial
    if any(set(pair) != set(configurations) for pair in by_instance.values()):
        raise ValueError('unpaired configuration coverage')
    index = json.loads((dataset_root / 'instances.index.json').read_text())
    index = [item for item in index if item['instanceId'] in by_instance]
    if {i['instanceId'] for i in index} != set(by_instance):
        raise ValueError('dataset index does not cover experiment population')
    groups, variants = defaultdict(set), defaultdict(set)
    languages = defaultdict(set)
    for item in index:
        groups[item['normalizedLanguage']].add(item['baseId'])
        languages[item['baseId']].add(item['normalizedLanguage'])
        variants[item['baseId']].add(item['requestedContextTokens'])
    if any(len(v) != 1 for v in languages.values()):
        raise ValueError('each target requires one language')
    if isinstance(definition.split, InstanceSplit):
        profile = definition.sizeProfile
        split = instance_split(definition.split, definition_path.parent, index, profile)
        listed = set(split['calibrationInstances']) | set(split['evaluationInstances'])
    else:
        profile = size_profile(variants)
        rng = random.Random(definition.split.seed)
        calibration = []
        for language in sorted(groups):
            targets = sorted(groups[language])
            if len(targets) <= definition.split.calibrationTargetsPerLanguage:
                raise ValueError('each language must retain held-out targets')
            calibration.extend(rng.sample(targets, definition.split.calibrationTargetsPerLanguage))
        split = {'calibration': sorted(calibration), 'heldOut': sorted(set(variants) - set(calibration)),
                 **definition.split.model_dump()}
        listed = {item['instanceId'] for item in index}
    requests = {}
    for item in index:
        if item['instanceId'] not in listed:
            continue
        pair = by_instance[item['instanceId']]
        first = pair[configurations[0]]
        for candidate in pair.values():
            for field in ('params', 'parameters', 'taskStatement', 'contextBlocks', 'validationConfig'):
                if getattr(first, field) != getattr(candidate, field):
                    raise ValueError(f'unpaired setting: {field}')
        context = adapter.get_context(first.instanceId, first.taskId, 'code').content
        variant = f"{item['requestedContextTokens'] // 1024}k"
        features = prepare_request_features(1, len(context.encode()), variant, profile)
        requests[first.instanceId] = {'instanceId': first.instanceId, 'target': item['baseId'],
            'language': item['normalizedLanguage'], 'variant': variant, 'sizeBin': str(features.size_bin),
            'candidates': {cid: asdict(initial_budget(pair[cid], adapter, context_limit=definition.contextLimit,
                            output_reservation=definition.outputReservation)) for cid in configurations},
            'trials': {cid: pair[cid].model_dump(mode='json') for cid in configurations}}
    episodes = []
    for si, seed in enumerate(definition.seeds):
        if isinstance(definition.split, InstanceSplit):
            order = split['calibrationInstances'][:]
            random.Random(seed).shuffle(order)
        else:
            order = [r['instanceId'] for r in ordered_workload(index, split['calibration'], seed)]
        for repetition in range(1, definition.repeats + 1):
            offset = (si + repetition - 1) % len(configurations)
            for cid in configurations[offset:] + configurations[:offset]:
                identity = {'configuration': cid, 'seed': seed, 'repeat': repetition}
                episodes.append({**identity, 'id': digest(identity)[:24], 'workload': order,
                                 'policy': {'type': 'fixed', 'configuration': cid}, 'scenario': []})
    manifest = {'provisioningArtifactVersion': 2, 'experimentId': experiment.id,
        'experimentPath': str(experiment_path), 'dataset': provenance.model_dump(mode='json'),
        'configurations': {cid: experiment.configurations[cid].model_dump(mode='json') for cid in configurations},
        'surfaces': {k: v.model_dump(mode='json') for k, v in experiment.surfaces.items()},
        'evaluation': experiment.evaluation.model_dump(mode='json'),
        'trace': experiment.trace.model_dump(mode='json'), 'artifacts': experiment.artifacts.model_dump(mode='json')}
    plan = {'schemaVersion': VERSION, 'kind': 'baseline', 'definition': definition.model_dump(exclude_none=True),
        'experimentPath': str(experiment_path), 'experimentHash': file_hash(experiment_path),
        'datasetRoot': str(dataset_root), 'datasetHash': tree_hash(dataset_root), 'sources': measurement_sources(),
        'configurations': configurations, 'index': index, 'split': split, 'sizeProfile': profile, 'requests': requests,
        'episodes': episodes, 'manifest': manifest, 'estimates': {},
        'budget': {'contextLimit': definition.contextLimit, 'outputReservation': definition.outputReservation,
                   'tokenizer': 'utf8-byte-upper-bound', 'provenance': 'estimated', 'serializationAllowance': 256}}
    output = Path(output).resolve()
    with episode_lock(output):
        if any(p.name != '.episode.lock' for p in output.iterdir()):
            raise ValueError('prepare requires fresh output')
        sealed_write(output / 'prepared.json', plan)
    return {'prepared': str(output / 'prepared.json'), 'episodes': len(episodes)}


def instance_split(split, base, index, profile):
    """Explicit calibration and evaluation instances; a target's instances stay on one side."""
    known = {item['instanceId']: item for item in index}
    entries = json.loads((base / split.calibrationInstances).read_text())
    evaluation = json.loads((base / split.evaluationInstances).read_text())
    calibration = [e if isinstance(e, str) else e['instance'] for e in entries]
    weights = {e['instance']: e['weight'] for e in entries if isinstance(e, dict) and 'weight' in e}
    if any(not isinstance(e, (str, dict)) or (isinstance(e, dict) and set(e) - {'instance', 'weight'})
           for e in entries) or not all(isinstance(e, str) for e in evaluation):
        raise ValueError('instance lists hold instance IDs (calibration entries may carry a weight)')
    if weights and (set(weights) != set(calibration) or any(
            isinstance(w, bool) or not isinstance(w, (int, float)) or not w > 0 for w in weights.values())):
        raise ValueError('weights must be positive and given for every calibration instance or none')
    for name, ids in (('calibration', calibration), ('evaluation', evaluation)):
        if not ids or len(set(ids)) != len(ids):
            raise ValueError(f'{name} instances must be non-empty and unique')
        if missing := sorted(set(ids) - set(known)):
            raise ValueError(f'{name} instances outside the experiment population: {missing[:5]}')
    targets = {name: {known[i]['baseId'] for i in ids} for name, ids in
               (('calibration', calibration), ('evaluation', evaluation))}
    if shared := sorted(targets['calibration'] & targets['evaluation']):
        raise ValueError(f'targets on both sides of the split: {shared[:5]}')
    if outside := sorted({known[i]['requestedContextTokens'] for i in calibration + evaluation} - SIZE_PROFILES[profile]):
        raise ValueError(f'sizes outside the {profile} profile: {outside}')
    return {'calibration': sorted(targets['calibration']), 'heldOut': sorted(targets['evaluation']),
            'calibrationInstances': sorted(calibration), 'evaluationInstances': sorted(evaluation),
            'weights': weights, 'calibrationFile': split.calibrationInstances,
            'evaluationFile': split.evaluationInstances}


def _mean(values, weights=None):
    if not values:
        return None
    if weights is None:
        return mean(values)
    return sum(v*w for v, w in zip(values, weights))/sum(weights)


def execute(*, prepared, resume=False, retry_uncertain=False, execution=None, checkpoint=lambda *_: None, seed=None):
    from ctxbench.adaptive.study_runner import run
    path = prepared_path(prepared)
    plan = sealed_read(path)
    verify(plan)
    if plan['kind'] != 'baseline':
        raise ValueError('expected baseline')
    if (path.parent / 'frozen.json').exists():
        raise ValueError('frozen baseline is immutable')
    episodes = [e for e in plan['episodes'] if seed is None or e['seed'] == seed]
    if not episodes:
        raise ValueError(f'no episode with seed {seed}')
    for episode in episodes:
        run(plan, episode, path.parent / 'episodes' / episode['id'], resume=resume,
            retry_uncertain=retry_uncertain,
            execution=execution, checkpoint=checkpoint)
    return {'episodes': len(episodes)}


def rows(path):
    if not path.exists():
        return []
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def freeze(*, prepared):
    from ctxbench.adaptive.study_runner import load_packets
    path = prepared_path(prepared)
    plan = sealed_read(path)
    verify(plan)
    if plan['kind'] != 'baseline':
        raise ValueError('expected baseline')
    with episode_lock(path.parent):
        if (path.parent / 'frozen.json').exists():
            raise ValueError('frozen baseline is immutable')
        observations, artifacts, sessions = [], {}, []
        for episode in plan['episodes']:
            root = path.parent / 'episodes' / episode['id']
            packets = load_packets(root)
            if len(packets) != len(episode['workload']) or any(p['state'] != 'completed' for p in packets):
                raise ValueError('incomplete baseline execution')
            sessions.append({'episode': episode['id'], 'startedAt': packets[0]['startedAt'],
                             'completedAt': packets[-1]['completedAt'],
                             'uncertainRetries': sum(p['uncertainRetries'] for p in packets)})
            evaluations = rows(root / 'evals.jsonl')
            evaluated = {r['trialId']: r for r in evaluations}
            if len(evaluated) != len(evaluations):
                raise ValueError('duplicate baseline evaluations')
            for packet in packets:
                result = packet['result']
                if result is None:
                    raise ValueError('baseline has unserved requests; cannot freeze')
                evaluation = evaluated.get(result['trialId'])
                if plan['manifest']['evaluation']['enabled'] and (
                    not evaluation or evaluation.get('status') not in ('evaluated', 'skipped') or
                    (result['status'] == 'success' and evaluation.get('status') != 'evaluated')
                ):
                    raise ValueError('incomplete baseline evaluation')
                passed = None if evaluation is None else (evaluation.get('outcome') or {}).get('passed')
                observations.append({**packet['observation'], 'configuration': episode['configuration'],
                    'instanceId': packet['instanceId'],
                    'sizeBin': plan['requests'][packet['instanceId']]['sizeBin'],
                    'evaluation': evaluation, 'passed': passed, 'episode': episode['id'], 'trialId': result['trialId']})
            for artifact in sorted(p for p in root.rglob('*') if p.is_file() and not p.name.startswith('.')):
                artifacts[str(artifact.relative_to(path.parent))] = file_hash(artifact)
        estimates, quality = {}, {}
        weights = plan['split'].get('weights') or {}
        weight = (lambda o: weights[o['instanceId']]) if weights else None
        for cid in plan['configurations']:
            estimates[cid] = {}
            scored = [o['passed'] for o in observations if o['configuration'] == cid and type(o['passed']) is bool]
            quality[cid] = {'passRate': mean(scored) if scored else None,
                            'evaluated': len(scored), 'passed': sum(scored)}
            for size in (('small', 'medium', 'large') if plan['sizeProfile'] == 'long64' else ('small', 'large')):
                sample = [o for o in observations if o['configuration'] == cid and o['sizeBin'] == size]
                success = [o for o in sample if o['status'] == 'success']
                known = [o for o in sample if o['tokens']['value'] is not None]
                tokens = [o['tokens']['value'] for o in known]
                scored_size = [o['passed'] for o in sample if type(o['passed']) is bool]
                w = (lambda rows: [weight(o) for o in rows]) if weight else (lambda rows: None)
                estimates[cid][size] = {'latencyMs': _mean([o['durationMs'] for o in success], w(success)),
                    'tokens': _mean(tokens, w(known)), 'observations': len(sample),
                    'successes': len(success), 'failures': len(sample)-len(success),
                    'usageCoverage': len(tokens), 'knownTokenTotal': sum(tokens) if tokens else None,
                    'passRate': mean(scored_size) if scored_size else None, 'evaluationCoverage': len(scored_size),
                    'provenance': 'estimated',
                    'estimator': 'weighted-observations-v1' if weights else 'all-observations-v1'}
        frozen = {'schemaVersion': VERSION, 'kind': 'frozen-baseline', 'preparedDigest': digest(plan),
                  'plan': plan, 'artifacts': artifacts, 'sessions': sessions,
                  'observations': observations, 'estimates': estimates, 'quality': quality}
        sealed_write(path.parent / 'frozen.json', frozen)
    return {'frozen': str(path.parent / 'frozen.json'), 'observations': len(observations)}
