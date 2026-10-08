"""Between-request execution with replayable policy state and durable outcomes."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter, time
from uuid import uuid4
import subprocess

from ctxbench.adapters.repoqa.study import digest, pair_trials, tree_hash
from ctxbench.benchmark.executor import execute_runspec
from ctxbench.benchmark.models import TrialResult, TrialSpec, RunTiming
from ctxbench.benchmark.provisioning import validate_artifact_directory
from .policy import AdaptivePolicy, FixedPolicy, PolicyConfig, RouterPolicy
from .recovery import episode_lock, project_json, project_rows, read, sealed_read, sealed_write, write
from .sidecars import DecisionRecord, DecisionSidecar, MetricRecord, RunMetadata, TokenRecord
from .types import (Candidate, EstimateKey, Observation, PolicyState, Provenance,
                    RequestFeatures, TokenUsage, INLINE_CONFIGURATION, LOCAL_MCP_CONFIGURATION)


@dataclass(frozen=True)
class EpisodeRequest:
    request_id: str
    features: RequestFeatures
    trial_ids: tuple[str, ...]
    candidates: tuple[Candidate, ...]
    target: str = ''
    language: str = ''


def make_policy(arm, calibration, config):
    state = PolicyState(arm, calibration=calibration)
    if arm in ('always-inline', 'always-local-mcp'):
        return FixedPolicy(state, INLINE_CONFIGURATION if arm == 'always-inline' else LOCAL_MCP_CONFIGURATION)
    if arm == 'frozen-router':
        return RouterPolicy(state, config)
    if arm == 'adaptive-router':
        return AdaptivePolicy(state, config)
    raise ValueError(f'unknown policy: {arm}')


def source_identity():
    root = Path(__file__).resolve().parents[3]
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    paths = sorted(list((root / 'src/ctxbench').rglob('*.py')) + list((root / 'tools/repoqa').glob('*.py')))
    paths += [root / relative for relative in ('pyproject.toml', 'uv.lock', 'tools/repoqa/pyproject.toml',
               'tools/repoqa/uv.lock', 'tools/repoqa/repoqa_python') if (root / relative).is_file()]
    return {'revision': revision, 'files': {str(p.relative_to(root)): digest(p.read_text()) for p in paths}}


def error_result(trial, error, started, finished, duration):
    fields = {k: getattr(trial, k) for k in TrialResult.model_fields if hasattr(trial, k) and k != 'trace'}
    return TrialResult(**fields, response='', status='error', errorMessage=str(error),
                       timing=RunTiming(startedAt=started, finishedAt=finished, durationMs=int(duration)))


def _iso(seconds):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def _project(root, packets, checkpoint):
    trials, responses, decisions, timings = [], [], [], []
    for packet in packets:
        decisions.append(packet['decision'])
        timings.append(packet['timing'])
        if packet['trial'] is not None:
            trial = TrialSpec.model_validate(packet['trial'])
            result = TrialResult.model_validate(packet['result'])
            trials.append(trial.to_persisted_artifact())
            trace_ref = f'traces/executions/{result.trialId}.json'
            project_json(root / trace_ref, {'experimentId': result.experimentId, 'trialId': result.trialId,
                                         'taskId': result.taskId, 'task': 'responses',
                                         'trace': result.trace.model_dump(mode='json')})
            checkpoint('trace_projection', packet['sequenceIndex'])
            responses.append(result.to_persisted_artifact(trace_ref=trace_ref))
    for name, rows in [('trials', trials), ('responses', responses), ('decisions', decisions),
                       ('controller-timings', timings)]:
        project_rows(root / f'{name}.jsonl', rows)
        checkpoint(name + '_projection', len(packets))


def run_episode(candidate_trials: list[TrialSpec], workload: list[EpisodeRequest], calibration: dict,
                policy: str, scenario: str, output_directory: str | Path, *, metadata: RunMetadata,
                engine=None, execution=execute_runspec, monotonic=perf_counter, wall_clock=time,
                resume=False, retry_uncertain=False, policy_config=None, checkpoint=lambda *_: None,
                runtime_decorator=None, manifest=None):
    """Resume only between requests. BaseException models an interrupted process.

    Execution callbacks follow execute_runspec(trial, engine, **kwargs). No
    evaluation callback exists: frozen observations alone rebuild controller state.
    """
    root = Path(output_directory).resolve()
    pair_trials(candidate_trials)
    catalog = {t.trialId: t for t in candidate_trials}
    if len({r.request_id for r in workload}) != len(workload):
        raise ValueError('duplicate request identity')
    for index, request in enumerate(workload, 1):
        if request.features.sequence_index != index:
            raise ValueError('noncontiguous workload')
        trials = [catalog[t] for t in request.trial_ids]
        if len(trials) != 2 or {t.configurationId for t in trials} != {c.configuration_id for c in request.candidates}:
            raise ValueError('request candidates do not match trials')
        if len({(t.taskId, t.instanceId, t.provider, t.modelId, t.repeatIndex) for t in trials}) != 1:
            raise ValueError('request candidates are not paired')
    if metadata.policy != policy or metadata.scenario != scenario or metadata.policy_version != '2':
        raise ValueError('run metadata identity mismatch')
    config = policy_config or PolicyConfig(metadata.latency_objective_ms)
    controller = make_policy(policy, calibration, config)
    dataset_roots = sorted({t.dataset.materialized_path or t.dataset.origin for t in candidate_trials})
    dataset_hashes = {str(path): tree_hash(Path(path)) for path in dataset_roots if path and Path(path).is_dir()}
    config_hashes = {t.experimentPath: digest(Path(t.experimentPath).read_text()) for t in candidate_trials
                     if t.experimentPath and Path(t.experimentPath).is_file()}
    identity = {'datasetHashes': dataset_hashes, 'configurationFiles': config_hashes, 'metadata': metadata.model_dump(mode='json'), 'sources': source_identity(),
                'catalog': [t.model_dump(mode='json') for t in candidate_trials],
                'workload': [asdict(r) for r in workload], 'policyConfig': asdict(config),
                'calibration': sorted([{'key': asdict(k), 'estimate': asdict(v)} for k, v in calibration.items()],
                                      key=lambda r: (r['key']['configuration_id'], r['key']['size_bin']))}
    # Normalize enum/tuple representations before comparing persisted identities.
    import json
    identity = json.loads(json.dumps(identity))
    if manifest is None:
        manifest = {'provisioningArtifactVersion': 2, 'experimentId': candidate_trials[0].experimentId,
                    'dataset': candidate_trials[0].dataset.model_dump(mode='json'),
                    'configurations': {t.configurationId: {'strategy': t.strategy, 'representation': t.representation,
                                                          'surface': t.surface} for t in candidate_trials},
                    'surfaces': {t.surface: t.surfaceSpec for t in candidate_trials},
                    'evaluation': {'enabled': True, 'judges': []}}
    identity['manifest'] = manifest
    with episode_lock(root):
        identity_path = root / 'recovery/identity.json'
        if identity_path.exists():
            if not resume:
                raise ValueError('episode already exists; use resume')
            if sealed_read(identity_path) != identity:
                raise ValueError('episode fingerprint mismatch; inputs or source changed')
        else:
            if resume or any(p.name != '.episode.lock' for p in root.iterdir()):
                raise ValueError('missing episode identity or nonempty output')
            sealed_write(identity_path, identity)
        project_json(root / 'manifest.json', manifest)
        project_json(root / 'adaptive-run.json', metadata.model_dump(mode='json'))
        lifecycle_path = root / 'lifecycle.json'
        lifecycle = read(lifecycle_path) if lifecycle_path.exists() else {'schemaVersion': 1, 'sessions': [], 'events': []}
        packets = []
        files = sorted((root / 'recovery').glob('request-*.json'))
        if len(files) > len(workload):
            raise ValueError('unexpected request packets')
        pending = None
        for i, path in enumerate(files, 1):
            if path.name != f'request-{i:04d}.json':
                raise ValueError('noncontiguous recovery history')
            packet = sealed_read(path)
            request = workload[i - 1]
            decision = controller.decide(request.features, request.candidates)
            expected = DecisionRecord.from_decision(decision).model_dump(mode='json')
            if packet['features'] != json.loads(json.dumps(asdict(request.features))) or packet['candidates'] != json.loads(json.dumps([asdict(c) for c in request.candidates])):
                raise ValueError('invalid saved request features/candidates')
            if packet['sequenceIndex'] != i or packet['requestId'] != request.request_id or packet['selection'] != expected:
                raise ValueError('saved decision differs from policy replay')
            if packet['state'] == 'started':
                if i != len(files):
                    raise ValueError('unfinished request precedes completed history')
                pending = packet
                break
            if packet['state'] != 'completed':
                raise ValueError('invalid request recovery state')
            sidecar = DecisionSidecar.model_validate(packet['decision'])
            if sidecar.status == 'selected' or sidecar.decision.model_dump(mode='json') != expected:
                raise ValueError('invalid terminal decision')
            if (sidecar.request_id != request.request_id or sidecar.policy != policy
                    or sidecar.policy_version != '2' or sidecar.trial_id != (packet['trial']['trialId'] if packet['trial'] else None)):
                raise ValueError('invalid terminal identity')
            selected = decision.selected_configuration
            expected_trial = next((catalog[t] for t in request.trial_ids if catalog[t].configurationId == selected), None)
            if selected:
                trial = TrialSpec.model_validate(packet['trial'])
                result = TrialResult.model_validate(packet['result'])
                if trial.model_dump(mode='json') != expected_trial.model_copy(update={'outputRoot': str(root)}, deep=True).model_dump(mode='json'):
                    raise ValueError('recovered trial differs from selected catalog entry')
                if result.configurationId != selected or result.metadata != trial.metadata:
                    raise ValueError('recovered result treatment differs')
                if trial.trialId != expected_trial.trialId or result.trialId != trial.trialId or result.status != sidecar.status:
                    raise ValueError('invalid recovered result')
                observation = Observation(selected, request.features.size_bin, sidecar.status,
                                          sidecar.end_to_end_duration_ms.value,
                                          TokenUsage(sidecar.tokens.value, sidecar.tokens.provenance))
                if asdict(observation) != packet['observation']:
                    raise ValueError('invalid recovered observation')
                controller.observe(observation)
            elif packet['trial'] is not None or packet['result'] is not None or packet['observation'] is not None:
                raise ValueError('unserved packet contains execution')
            timing = packet['timing']
            if (timing.get('schemaVersion') != 1 or timing.get('requestId') != request.request_id
                    or timing.get('sequenceIndex') != i or timing.get('provenance') != 'measured'
                    or not isinstance(timing.get('controllerDurationMs'), (int, float))
                    or not __import__('math').isfinite(timing['controllerDurationMs']) or timing['controllerDurationMs'] < 0):
                raise ValueError('invalid recovered timing')
            packets.append(packet)
        _project(root, packets, checkpoint)
        if len(packets) == len(workload):
            validate_artifact_directory(root)
            lifecycle['completed'] = True
            lifecycle['lastDurableActivity'] = packets[-1]['completedAt'] if packets else lifecycle.get('lastDurableActivity')
            write(lifecycle_path, lifecycle)
            return packets
        if pending and pending['executionStarted'] and not retry_uncertain:
            raise ValueError('uncertain provider attempt; use retry_uncertain to permit a possible duplicate call')
        now = wall_clock()
        durable_times = [p['completedAt'] for p in packets]
        if pending:
            durable_times.append(pending['startedAt'])
        previous = max(durable_times, default=lifecycle.get('lastDurableActivity'))
        if resume:
            lifecycle['events'].append({'type': 'recovery', 'completedRequests': len(packets),
                                        'pendingSequenceIndex': pending['sequenceIndex'] if pending else None})
        lifecycle['sessions'].append({'id': str(uuid4()), 'startedAt': now, 'resumed': resume,
                                      'downtimeMs': max(0, (now - previous) * 1000) if previous is not None else None,
                                      'downtimeProvenance': 'estimated' if previous is not None else 'unavailable'})
        if pending and pending['executionStarted']:
            lifecycle['events'].append({'type': 'uncertain-retry', 'sequenceIndex': pending['sequenceIndex'],
                                        'priorUsage': None, 'priorUsageProvenance': 'unavailable'})
        write(lifecycle_path, lifecycle)
        start_index = len(packets) + 1
        for i in range(start_index, len(workload) + 1):
            request = workload[i - 1]
            controller_start = monotonic()
            if pending and i == start_index:
                # decide() already ran while restoring the pending selection.
                decision_record = pending['selection']
                selected = decision_record['selectedConfiguration']
            else:
                decision = controller.decide(request.features, request.candidates)
                decision_record = DecisionRecord.from_decision(decision).model_dump(mode='json')
                selected = decision.selected_configuration
            overhead = (pending['controllerDurationMs'] if pending and i == start_index
                        else max(0, (monotonic() - controller_start) * 1000))
            trial = next((catalog[t] for t in request.trial_ids if catalog[t].configurationId == selected), None)
            if trial:
                trial = trial.model_copy(update={'outputRoot': str(root)}, deep=True)
            packet = {'sequenceIndex': i, 'requestId': request.request_id, 'selection': decision_record,
                      'features': asdict(request.features), 'candidates': [asdict(c) for c in request.candidates],
                      'state': 'started', 'executionStarted': bool(pending and pending['executionStarted']),
                      'startedAt': wall_clock(), 'controllerDurationMs': overhead, 'uncertainRetries': (pending.get('uncertainRetries', 0) + 1
                                       if pending and pending['executionStarted'] else 0)}
            packet_path = root / f'recovery/request-{i:04d}.json'
            sealed_write(packet_path, packet)
            checkpoint('selection_saved', i)
            duration, result, observation = None, None, None
            if trial:
                packet['executionStarted'] = True
                sealed_write(packet_path, packet)
                checkpoint('execution_started', i)
                started = wall_clock()
                outer_start = monotonic()
                try:
                    kwargs = {}
                    if runtime_decorator:
                        kwargs['local_mcp_runtime_decorator'] = runtime_decorator(i)
                    result = execution(trial, engine, **kwargs)
                except Exception as exc:
                    duration = max(0, (monotonic() - outer_start) * 1000)
                    result = error_result(trial, exc, _iso(started), _iso(wall_clock()), duration)
                if duration is None:
                    duration = max(0, (monotonic() - outer_start) * 1000)
                if result.trialId != trial.trialId or result.configurationId != trial.configurationId:
                    raise ValueError('execution returned a different trial')
                checkpoint('execution_finished', i)
                token_value = result.usage.get('totalTokens')
                tokens = TokenUsage(token_value, Provenance.REPORTED if token_value is not None else Provenance.UNAVAILABLE)
                observation = Observation(selected, request.features.size_bin, result.status, duration, tokens)
            else:
                tokens = TokenUsage(None, Provenance.UNAVAILABLE)
            status = result.status if result else 'unserved'
            sidecar = DecisionSidecar(requestId=request.request_id, trialId=trial.trialId if trial else None,
                                      policy=policy, policyVersion='2', decision=decision_record, status=status,
                                      endToEndDurationMs=MetricRecord(value=duration,
                                          provenance=Provenance.MEASURED if duration is not None else Provenance.UNAVAILABLE,
                                          observationCount=1 if duration is not None else 0),
                                      tokens=TokenRecord(**asdict(tokens)), error=result.errorMessage if result else None)
            observe_start = monotonic()
            if observation:
                controller.observe(observation)
            observe_duration = max(0, (monotonic() - observe_start) * 1000)
            packet.update(state='completed', trial=trial.model_dump(mode='json') if trial else None,
                          result=result.model_dump(mode='json') if result else None,
                          observation=asdict(observation) if observation else None,
                          decision=sidecar.model_dump(mode='json'),
                          timing={'schemaVersion': 1, 'requestId': request.request_id, 'sequenceIndex': i,
                                  'controllerDurationMs': overhead + observe_duration, 'selectionDurationMs': overhead,
                                  'observationDurationMs': observe_duration, 'provenance': 'measured'},
                          completedAt=wall_clock())
            sealed_write(packet_path, packet)
            checkpoint('outcome_saved', i)
            packets.append(packet)
            _project(root, packets, checkpoint)
            lifecycle['lastDurableActivity'] = packet['completedAt']
            write(lifecycle_path, lifecycle)
            pending = None
        validate_artifact_directory(root)
        lifecycle['completed'] = True
        write(lifecycle_path, lifecycle)
        return packets
