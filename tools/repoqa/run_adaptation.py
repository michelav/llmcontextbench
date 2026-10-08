#!/usr/bin/env python3
"""Research-only RepoQA workflow. Preparation/freeze/analysis never call providers."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import json
import subprocess

from ctxbench.adapters.repoqa.package import RepoQADatasetAdapter
from ctxbench.adapters.repoqa.study import (CONFIGURATIONS, EPISODE_SEEDS, digest, initial_budget,
                                           ordered_workload, pair_trials, split_targets, tree_hash)
from ctxbench.adapters.repoqa.workload import prepare_request_features
from ctxbench.adaptive.calibration import DELAYS_MS, DelayedRuntime, delay_at, freeze_calibration, load_estimates
from ctxbench.adaptive.recovery import sealed_read, sealed_write
from ctxbench.adaptive.runner import EpisodeRequest, run_episode, source_identity
from ctxbench.adaptive.sidecars import RunMetadata
from ctxbench.adaptive.types import Candidate, ContextFit, Provenance, RequestFeatures, SizeBin
from ctxbench.benchmark.models import DatasetProvenance, Experiment, TrialSpec
from ctxbench.benchmark.runspec_generator import generate_runspecs

ARMS = ('always-inline', 'always-local-mcp', 'frozen-router', 'adaptive-router')


def prepare(args):
    experiment_path = Path(args.experiment).resolve()
    payload = json.loads(experiment_path.read_text())
    experiment = Experiment.model_validate(payload)
    root = Path(experiment.dataset.root).resolve()
    adapter = RepoQADatasetAdapter(root)
    provenance = DatasetProvenance(id=adapter.identity(), version=adapter.version(), materialized_path=str(root))
    trials = generate_runspecs(experiment, experiment_path.parent, adapter, provenance, experiment_path=experiment_path)
    for trial in trials:
        configured = trial.params.get('max_output_tokens', trial.params.get('max_tokens'))
        if configured is not None and configured != args.output_reservation:
            raise ValueError('output reservation differs from configured max tokens')
        trial.params['max_tokens'] = args.output_reservation
    pairs = pair_trials(trials)
    if {t.repeatIndex for t in trials} != {1, 2}:
        raise ValueError('preparation requires exactly two calibration repeats')
    index = json.loads((root / 'instances.index.json').read_text())
    split = split_targets(index)
    if len(split['calibration']) != 4 or len(split['heldOut']) != 16 or len(index) != 80:
        raise ValueError('prototype requires 20 targets / 80 variants')
    if {t.instanceId for t in trials} != {i['instanceId'] for i in index}:
        raise ValueError('catalog does not cover the exact dataset population')
    tokenizer = None
    tokenizer_name = 'utf8-byte-upper-bound'
    try:
        import tiktoken
        encoding = tiktoken.encoding_for_model(trials[0].modelName)
        tokenizer = lambda text: encoding.encode(text, disallowed_special=())
        tokenizer_name = encoding.name
    except (ImportError, KeyError):
        pass
    requests = {}
    for pair in pairs.values():
        sample = next(iter(pair.values()))
        item = next(i for i in index if i['instanceId'] == sample.instanceId)
        context = adapter.get_context(sample.instanceId, sample.taskId, 'code').content
        if not isinstance(context, str):
            raise ValueError('RepoQA code context must be text')
        candidates = tuple(initial_budget(t, adapter, context_limit=args.context_limit,
                                         output_reservation=args.output_reservation, tokenizer=tokenizer)
                           for t in pair.values())
        requests[f'{sample.instanceId}:{sample.repeatIndex}'] = {
            'trialIds': [t.trialId for t in pair.values()], 'candidates': [asdict(c) for c in candidates],
            'contextBytes': len(context.encode()), 'variant': f"{item['requestedContextTokens'] // 1024}k",
            'target': item['baseId'], 'language': item['normalizedLanguage']}
    held = {str(seed): ordered_workload(index, split['heldOut'], seed) for seed in EPISODE_SEEDS}
    calibration_order = ordered_workload(index, split['calibration'], 20260929)
    study = {'schemaVersion': 1, 'datasetRoot': str(root), 'datasetHash': tree_hash(root),
             'experimentPath': str(experiment_path), 'experimentHash': digest(payload),
             'split': split, 'trials': [t.model_dump(mode='json') for t in trials], 'requests': requests,
             'heldOut': held, 'calibrationOrder': calibration_order,
             'budget': {'contextLimit': args.context_limit, 'outputReservation': args.output_reservation,
                        'tokenizer': tokenizer_name, 'serializationAllowance': 256,
                        'scope': 'initial prompt only; tool-loop growth may exceed limit'},
             'sources': source_identity(), 'costProjection': {'heldOutRequests': 1536,
                 'baselineExecutions': 64, 'delayExecutions': 128, 'currency': None, 'provenance': 'unavailable'}}
    path = Path(args.output) / 'prepared.json'
    if path.exists():
        raise ValueError('preparation requires a fresh output')
    sealed_write(path, study)
    return {'prepared': str(path), 'hash': digest(study)}


def verify_study(study):
    if tree_hash(Path(study['datasetRoot'])) != study['datasetHash']:
        raise ValueError('dataset fingerprint mismatch')
    if digest(json.loads(Path(study['experimentPath']).read_text())) != study['experimentHash']:
        raise ValueError('experiment fingerprint mismatch')
    if source_identity() != study['sources']:
        raise ValueError('source revision or uncommitted files changed since preparation')


def workload_for(study, order, repeats):
    workload = []
    for repeat in repeats:
        for item in order:
            row = study['requests'][f"{item['instanceId']}:{repeat}"]
            index = len(workload) + 1
            candidates = tuple(Candidate(c['configuration_id'], c['executable'],
                ContextFit(**{**c['context_fit'], 'provenance': Provenance(c['context_fit']['provenance'])}))
                for c in row['candidates'])
            workload.append(EpisodeRequest(f"{item['instanceId']}:{repeat}",
                prepare_request_features(index, row['contextBytes'], row['variant']), tuple(row['trialIds']),
                candidates, row['target'], row['language']))
    return workload


def calibration_packets(root):
    packets = []
    for path in sorted(Path(root).glob('recovery/request-*.json')):
        packet = sealed_read(path)
        if packet['state'] != 'completed':
            raise ValueError('calibration episode is incomplete')
        packets.append(packet)
    identity = sealed_read(Path(root) / 'recovery/identity.json')
    if len(packets) != len(identity['workload']):
        raise ValueError('calibration episode is incomplete')
    return packets


def frozen_inputs(study, output):
    base = Path(output) / 'calibration'
    baseline = calibration_packets(base / 'baseline/always-inline') + calibration_packets(base / 'baseline/always-local-mcp')
    delayed = {delay: calibration_packets(base / f'delay-{delay}/always-local-mcp') for delay in DELAYS_MS}
    return baseline, delayed


def freeze(args):
    study = sealed_read(Path(args.prepared))
    verify_study(study)
    baseline, delayed = frozen_inputs(study, args.output)
    frozen = freeze_calibration(baseline, delayed, prepared_hash=digest(study), application_slo_ms=args.application_slo_ms)
    frozen['sources'] = source_identity()
    frozen['studyHash'] = digest(study)
    tokens = [p['decision']['tokens']['value'] for p in baseline]
    frozen['costProjection'] = {'heldOutRequests': 1536,
        'projectedTokens': sum(tokens) / len(tokens) * 1536 if all(t is not None for t in tokens) else None,
        'provenance': 'estimated' if all(t is not None for t in tokens) else 'unavailable',
        'currency': None, 'priceSource': None}
    path = Path(args.output) / 'frozen.json'
    if path.exists():
        raise ValueError('frozen calibration already exists')
    sealed_write(path, frozen)
    return frozen


def scorer_smoke():
    """Use the existing isolated scorer environment; never install dependencies."""
    wrapper = Path(__file__).with_name('repoqa_python')
    helper = Path(__file__).with_name('score_response.py')
    code = 'def target():\n    return 1\n'
    request = {'response': code, 'native_task': {'name': 'target', 'language': 'python'},
               'repo_info': {'content': {'example.py': code}, 'needles': [
                   {'name': 'target', 'path': 'example.py', 'start_line': 0, 'end_line': 2}]},
               'ignore_comments': True}
    completed = subprocess.run([str(wrapper), str(helper)], input=json.dumps(request),
                               capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError('scorer smoke failed: ' + completed.stderr.strip())
    score = json.loads(completed.stdout)
    if score['verdict'] != 'best_match' or score['bestSimilarScore'] < .99:
        raise ValueError('real scorer smoke failed')
    return score


def execute_operation(args, calibration=False):
    study = sealed_read(Path(args.prepared))
    verify_study(study)
    trials = [TrialSpec.model_validate(t) for t in study['trials']]
    if any(t.provider not in ('mock', 'echo') for t in trials) and not args.execute_providers:
        raise ValueError('provider execution requires --execute-providers after cost authorization')
    if any(t.provider not in ('mock', 'echo') for t in trials):
        import sys
        print('Provider execution spends API tokens, including multiple local-MCP steps. '
              'Use the prepared/frozen cost projections before authorizing runs.', file=sys.stderr)
        scorer_smoke()
    frozen, estimates = None, {}
    if not calibration:
        frozen = sealed_read(Path(args.output) / 'frozen.json')
        baseline, delayed = frozen_inputs(study, args.output)
        if (frozen['preparedHash'] != digest(study) or frozen['sources'] != source_identity()
                or frozen['baselineHash'] != digest(baseline)
                or frozen['delayHashes'] != {str(d): digest(delayed[d]) for d in DELAYS_MS}):
            raise ValueError('frozen provenance mismatch')
        if args.scenario not in frozen['scenarios']:
            raise ValueError('no qualifying delay; stationary results only')
        estimates = load_estimates(frozen)
    order = study['calibrationOrder'] if calibration else study['heldOut'][str(args.seed)]
    workload = workload_for(study, order, (1, 2) if calibration else (1,))
    arms = (('always-local-mcp',) if args.delay_ms else ('always-inline', 'always-local-mcp')) if calibration else (args.policy,)
    # Counterbalance policies across seeds for providers without cache-key support.
    offset = EPISODE_SEEDS.index(args.seed) if args.seed in EPISODE_SEEDS else 0
    counterbalanced = list(ARMS[offset:] + ARMS[:offset])
    if not calibration and args.policy == 'all':
        arms = tuple(counterbalanced)
    from ctxbench.ai.engine import Engine
    engine = Engine()
    outputs = []
    try:
        for arm in arms:
            scenario = 'stationary' if calibration else args.scenario
            delay = args.delay_ms if calibration else (frozen['selectedDelayMs'] or 0)
            objective = 0 if calibration else frozen['latencyObjectiveMs']
            folder = (Path(args.output) / 'calibration' / (f'delay-{delay}' if delay else 'baseline') / arm
                      if calibration else Path(args.output) / 'episodes' / scenario / str(args.seed) / arm)
            supports_keys = trials[0].provider.lower().startswith('openai')
            cache = {'behavior': 'isolated-key' if supports_keys else 'provider-default',
                     'counterbalancedOrder': counterbalanced, 'scope': f'{scenario}:{args.seed}:{arm}:{delay}'}
            # Model settings stay fixed; only supported cache partition keys differ by episode.
            episode_trials = [t.model_copy(update={'params': {**t.params,
                **({'prompt_cache_key': digest([cache['scope'], t.instanceId])} if supports_keys else {})}}, deep=True) for t in trials]
            metadata = RunMetadata(policy=arm, policyVersion='2', scenario=scenario, seed=args.seed,
                datasetProvenance={'hash': study['datasetHash'], 'split': study['split']},
                modelProvenance={'provider': trials[0].provider, 'modelName': trials[0].modelName,
                                 'params': trials[0].params, 'budget': study['budget']},
                configurationCatalog={t.configurationId: {'strategy': t.strategy, 'representation': t.representation,
                                                         'surface': t.surface} for t in trials},
                latencyObjectiveMs=objective, injectionSchedule=({'start': 1 if calibration else 21,
                    'end': len(workload) if calibration else 44, 'delayMs': delay},), cachePolicy=cache,
                codeRevision=source_identity()['revision'])
            def decorator(index):
                amount = delay if calibration else delay_at(index, scenario, delay)
                return lambda runtime: DelayedRuntime(runtime, amount)
            packets = run_episode(episode_trials, workload, estimates, arm, scenario, folder, metadata=metadata,
                engine=engine, resume=args.resume, retry_uncertain=args.retry_uncertain, runtime_decorator=decorator)
            outputs.append({'output': str(folder), 'completedRequests': len(packets)})
    finally:
        engine.close()
    return outputs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    prepare_parser = sub.add_parser('prepare')
    prepare_parser.add_argument('--experiment', default='experiment.repoqa-adaptive.json')
    prepare_parser.add_argument('--context-limit', type=int, required=True)
    prepare_parser.add_argument('--output-reservation', type=int, required=True)
    prepare_parser.add_argument('--output', required=True)
    for operation in ('calibrate', 'episode', 'freeze'):
        p = sub.add_parser(operation)
        p.add_argument('--prepared', required=True)
        p.add_argument('--output', required=True)
        if operation == 'freeze':
            p.add_argument('--application-slo-ms', type=float)
        else:
            p.add_argument('--resume', action='store_true')
            p.add_argument('--retry-uncertain', action='store_true')
            p.add_argument('--execute-providers', action='store_true', help='explicit paid execution opt-in')
            p.add_argument('--seed', type=int, choices=EPISODE_SEEDS, default=EPISODE_SEEDS[0])
            if operation == 'episode':
                p.add_argument('--policy', choices=ARMS + ('all',), required=True)
                p.add_argument('--scenario', choices=('stationary', 'degradation-recovery'), required=True)
            else:
                p.add_argument('--delay-ms', type=int, choices=(0,) + DELAYS_MS, default=0)
    p = sub.add_parser('analyze')
    p.add_argument('--output', required=True)
    p.add_argument('--bootstrap-replicates', type=int, default=10000)
    args = parser.parse_args(argv)
    if args.operation == 'prepare':
        result = prepare(args)
    elif args.operation == 'freeze':
        result = freeze(args)
    elif args.operation in ('calibrate', 'episode'):
        result = execute_operation(args, calibration=args.operation == 'calibrate')
    else:
        from ctxbench.adapters.repoqa.adaptation_analysis import analyze_study
        result = analyze_study(Path(args.output), bootstrap_replicates=args.bootstrap_replicates)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
