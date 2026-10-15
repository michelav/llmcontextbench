"""V3 episodes: durable request packets, strict replay and canonical projections.

Unknown interrupted attempts require a fresh collection; V3 does not automatically
retry potentially charged calls. Legacy retry behavior remains in runner.py.
"""
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter, sleep

from ctxbench.adapters.repoqa.study import digest
from ctxbench.ai.models.usage import account_tokens
from ctxbench.benchmark.models import TrialSpec
from ctxbench.benchmark.executor import execute_runspec
from ctxbench.benchmark.provisioning import validate_artifact_directory
from mcp.shared.exceptions import McpError
from .calibration import DelayedRuntime
from .recovery import episode_lock, sealed_read, sealed_write, project_json
from .runner import _project, error_result


def load_packets(root):
    packets = []
    for index, path in enumerate(sorted((Path(root) / 'recovery').glob('request-*.json')), 1):
        if path.name != f'request-{index:04d}.json':
            raise ValueError('noncontiguous request history')
        packet = sealed_read(path)
        if packet.get('schemaVersion') != 3 or packet['sequenceIndex'] != index:
            raise ValueError('invalid packet version or sequence')
        packets.append(packet)
    return packets


class MeasuredToolDelay(DelayedRuntime):
    def __init__(self, runtime, delay_ms, *, sleeper, monotonic):
        super().__init__(runtime, delay_ms, sleeper=sleeper)
        self.monotonic = monotonic
        self.calls = 0
        self.actual_ms = 0.0

    def call_tool(self, name, arguments):
        started = self.monotonic()
        self.sleeper(self.delay_ms / 1000)
        self.actual_ms += max(0, (self.monotonic()-started)*1000)
        self.calls += 1
        return self.runtime.call_tool(name, arguments)


def run(plan, episode, root, *, resume=False, retry_uncertain=False, execution=None, checkpoint=lambda *_: None,
        monotonic=perf_counter, sleeper=sleep):
    from .study_policy import Controller
    root = Path(root)
    identity = {'schemaVersion': 3, 'planDigest': digest(plan), 'episode': episode}
    engine = None
    controller = Controller(plan, episode)
    with episode_lock(root):
        identity_path = root / 'recovery/identity.json'
        if identity_path.exists():
            if not resume:
                raise ValueError('episode exists; use resume')
            if sealed_read(identity_path) != identity:
                raise ValueError('episode fingerprint mismatch')
        else:
            if any(p.name != '.episode.lock' for p in root.iterdir()):
                raise ValueError('nonempty episode without identity')
            sealed_write(identity_path, identity)
        project_json(root / 'manifest.json', plan['manifest'])
        packets = load_packets(root)
        if len(packets) > len(episode['workload']):
            raise ValueError('extra request packets')
        pending = packets[-1] if packets and packets[-1]['state'] == 'started' else None
        if pending:
            packets = packets[:-1]
            if pending.get('executionStarted') and not retry_uncertain:
                raise ValueError('uncertain interrupted attempt; retry_uncertain requires explicit authorization')
        for index, packet in enumerate(packets):
            if packet['instanceId'] != episode['workload'][index]:
                raise ValueError('request identity mismatch')
            decision = controller.decide(index)
            if packet['selection'] != decision:
                raise ValueError('saved selection differs from replay')
            if packet['state'] != 'completed':
                raise ValueError('unfinished request precedes completed history')
            if packet.get('uncertainRetries'):
                controller.unknown = True
            if 'attempts' in packet:
                _replay_attempts(controller, index, packet['attempts'], finished=True)
            else:
                controller.observe(packet['observation'])
            if packet['ledger'] != controller.ledger():
                raise ValueError('saved ledger differs from replay')
        _project(root, packets, checkpoint)
        if execution is None and len(packets) < len(episode['workload']):
            from ctxbench.ai.engine import Engine
            engine = Engine()
            execution = execute_runspec
        def make_trial(cid, params=None):
            original = plan['requests'][instance_of[0]]['trials'][cid]
            update = {'trialId': digest([identity['planDigest'], episode['id'], instance_of[0], cid]),
                      'outputRoot': str(root.resolve())}
            if params:
                update['params'] = {**original.get('params', {}), **params}
            return TrialSpec.model_validate(original).model_copy(update=update, deep=True)

        def execute_attempt(trial, cid, index, instance, uncertain):
            """One measured execution; injected delays are inside the measured duration."""
            delayed_runtimes = []
            delay_requested, delay_actual, thrown = 0, 0, None
            started = datetime.now(timezone.utc).isoformat()
            outer = monotonic()
            try:
                treatments = [d for d in episode['scenario'] if d['configuration'] == cid and
                              d['firstRequest'] <= index+1 <= d['lastRequest']]
                delay_requested = sum(d['delayMs'] for d in treatments if d['scope'] == 'request')
                delay_start = monotonic()
                if delay_requested:
                    sleeper(delay_requested / 1000)
                delay_actual = (monotonic()-delay_start)*1000
                tool_delay = sum(d['delayMs'] for d in treatments if d['scope'] == 'tool-call')
                kwargs = {}
                if tool_delay:
                    def decorate(runtime):
                        delayed = MeasuredToolDelay(runtime, tool_delay, sleeper=sleeper, monotonic=monotonic)
                        delayed_runtimes.append(delayed)
                        return delayed
                    kwargs['local_mcp_runtime_decorator'] = decorate
                result = execution(trial, engine, **kwargs)
            except Exception as exc:
                thrown = exc
                result = error_result(trial, exc, started, datetime.now(timezone.utc).isoformat(),
                                      (monotonic()-outer)*1000)
            duration = max(0, (monotonic()-outer)*1000)
            if result.trialId != trial.trialId or result.configurationId != cid:
                raise ValueError('execution result identity mismatch')
            metrics = result.trace.aiTrace.get('metrics', {})
            total, provenance, partial = account_tokens(result.provider, result.usage.get('totalTokens'),
                model_calls=metrics.get('modelCalls'), raw_response=result.trace.rawResponse,
                partial_total=metrics.get('totalTokens'), missing_total_estimate=metrics.get('totalTokensEstimated'))
            if uncertain:
                partial = (partial or 0) + (total or 0)
                total, provenance = None, 'unavailable'
            observation = {'configuration': cid, 'sizeBin': plan['requests'][instance]['sizeBin'],
                'status': result.status, 'durationMs': duration,
                'tokens': {'value': total, 'provenance': provenance, 'knownPartial': partial},
                'failures': classify_failures(result, thrown), 'sequenceIndex': index+1}
            return {'result': result, 'observation': observation, 'durationMs': duration,
                    'delayRequestedMs': delay_requested, 'delayActualMs': delay_actual,
                    'delayedRuntimes': delayed_runtimes}

        instance_of = [None]
        try:
            for index in range(len(packets), len(episode['workload'])):
                instance = episode['workload'][index]
                instance_of[0] = instance
                selection = controller.decide(index)
                retrying = pending is not None and index+1 == pending['sequenceIndex']
                if retrying and selection != pending['selection']:
                    raise ValueError('pending selection differs from policy replay')
                uncertain = bool(retrying and pending.get('executionStarted'))
                if uncertain:
                    controller.unknown = True
                cid = selection['configuration']
                trial = None
                if cid:
                    trial = make_trial(cid)
                if controller.policy['type'] == 'cascade':
                    packet = _cascade_request(controller, index, instance, selection, pending if retrying else None,
                                              uncertain, root, make_trial, execute_attempt, checkpoint)
                    packets.append(packet)
                    _project(root, packets, checkpoint)
                    pending = None
                    continue
                packet = {'schemaVersion': 3, 'sequenceIndex': index+1, 'instanceId': instance,
                          'selection': selection, 'state': 'started', 'executionStarted': False,
                          'uncertainRetries': 1 if uncertain else 0,
                          'startedAt': pending['startedAt'] if retrying else datetime.now(timezone.utc).isoformat()}
                packet_path = root / f'recovery/request-{index+1:04d}.json'
                sealed_write(packet_path, packet)
                checkpoint('selection_saved', index+1)
                result, duration, thrown = None, None, None
                delay_requested, delay_actual = 0, 0
                delayed_runtimes = []
                if uncertain and controller.policy['type'] == 'budget':
                    trial = None
                if trial:
                    packet['executionStarted'] = True
                    sealed_write(packet_path, packet)
                    checkpoint('execution_started', index+1)
                    outcome = execute_attempt(trial, cid, index, instance, uncertain)
                    checkpoint('execution_finished', index+1)
                    result, observation, duration = outcome['result'], outcome['observation'], outcome['durationMs']
                    delay_requested, delay_actual = outcome['delayRequestedMs'], outcome['delayActualMs']
                    delayed_runtimes = outcome['delayedRuntimes']
                else:
                    observation = None
                controller.observe(observation)
                decision = {'schemaVersion': 3, 'requestId': instance, 'sequenceIndex': index+1,
                            **selection, 'status': result.status if result else 'unserved',
                            'tokens': observation['tokens'] if observation else None,
                            'durationMs': duration, 'delayRequestedMs': delay_requested,
                            'delayActualMs': delay_actual,
                            'toolDelayRequestedMs': sum(r.calls*r.delay_ms for r in delayed_runtimes),
                            'toolDelayActualMs': sum(r.actual_ms for r in delayed_runtimes),
                            'toolCallsDelayed': sum(r.calls for r in delayed_runtimes),
                            'ledger': controller.ledger()}
                packet.update(state='completed', trial=trial.model_dump(mode='json') if trial else None,
                              result=result.model_dump(mode='json') if result else None,
                              observation=observation, decision=decision, ledger=controller.ledger(),
                              completedAt=datetime.now(timezone.utc).isoformat(),
                              timing={'schemaVersion': 3, 'sequenceIndex': index+1, 'durationMs': duration})
                sealed_write(packet_path, packet)
                checkpoint('outcome_saved', index+1)
                packets.append(packet)
                _project(root, packets, checkpoint)
                pending = None
            validate_artifact_directory(root)
            return packets
        finally:
            if engine:
                engine.close()


def _replay_attempts(controller, index, attempts, *, finished=False):
    """Re-observe saved attempts, mirroring every fallback query the live loop made."""
    for position, attempt in enumerate(attempts):
        if position:
            fallback = controller.decide_fallback(index, attempts[position-1]['observation'])
            if fallback is None or fallback['configuration'] != attempt['configuration']:
                raise ValueError('saved fallback differs from policy replay')
        controller.observe(attempt['observation'])
    if finished and attempts and len(attempts) <= len(controller.policy['fallbacks']):
        if controller.decide_fallback(index, attempts[-1]['observation']) is not None:
            raise ValueError('saved request stopped before a fallback the policy now requires')


def _combined_tokens(observations):
    """Sum per-attempt usage; any unknown attempt makes the total unknown with a known lower bound."""
    tokens = [o['tokens'] for o in observations]
    if all(t['value'] is not None for t in tokens):
        provenances = {t['provenance'] for t in tokens}
        return {'value': sum(t['value'] for t in tokens),
                'provenance': provenances.pop() if len(provenances) == 1 else 'derived', 'knownPartial': None}
    return {'value': None, 'provenance': 'unavailable',
            'knownPartial': sum(t['value'] if t['value'] is not None else (t['knownPartial'] or 0) for t in tokens)}


def _cascade_request(controller, index, instance, selection, pending, uncertain, root, make_trial,
                     execute_attempt, checkpoint):
    """Primary attempt plus at most the declared fallbacks, charged to the same request."""
    plan, policy = controller.plan, controller.policy
    packet_path = root / f'recovery/request-{index+1:04d}.json'
    saved = pending.get('attempts', []) if pending else []
    completed = [a for a in saved if a['state'] == 'completed']
    # Only the attempt interrupted after it started may have charged unknown usage.
    retry_position = len(completed) if len(saved) > len(completed) else None
    _replay_attempts(controller, index, completed)
    packet = {'schemaVersion': 3, 'sequenceIndex': index+1, 'instanceId': instance, 'selection': selection,
              'state': 'started', 'executionStarted': False, 'uncertainRetries': 1 if uncertain else 0,
              'startedAt': pending['startedAt'] if pending else datetime.now(timezone.utc).isoformat(),
              'attempts': completed}
    sealed_write(packet_path, packet)
    checkpoint('selection_saved', index+1)
    while len(completed) <= len(policy['fallbacks']):
        if not completed:
            cid, reason = selection['configuration'], selection['reason']
        else:
            fallback = controller.decide_fallback(index, completed[-1]['observation'])
            if fallback is None:
                break
            cid, reason = fallback['configuration'], fallback['reason']
        if cid is None:
            break
        params = ({'max_steps': policy['primaryMaxSteps']}
                  if policy.get('primaryMaxSteps') and cid == policy['primary'] else None)
        trial = make_trial(cid, params)
        attempt = {'configuration': cid, 'reason': reason, 'state': 'started',
                   'trial': trial.model_dump(mode='json')}
        packet.update(attempts=completed+[attempt], executionStarted=True)
        sealed_write(packet_path, packet)
        checkpoint('attempt_started', index+1)
        outcome = execute_attempt(trial, cid, index, instance, uncertain and len(completed) == retry_position)
        runtimes = outcome['delayedRuntimes']
        attempt.update(state='completed', result=outcome['result'].model_dump(mode='json'),
                       observation=outcome['observation'], durationMs=outcome['durationMs'],
                       delayRequestedMs=outcome['delayRequestedMs'], delayActualMs=outcome['delayActualMs'],
                       toolDelayRequestedMs=sum(r.calls*r.delay_ms for r in runtimes),
                       toolDelayActualMs=sum(r.actual_ms for r in runtimes),
                       toolCallsDelayed=sum(r.calls for r in runtimes))
        controller.observe(outcome['observation'])
        completed.append(attempt)
        packet.update(attempts=completed, executionStarted=False)
        sealed_write(packet_path, packet)
        checkpoint('attempt_saved', index+1)
    observations = [a['observation'] for a in completed]
    final = completed[-1] if completed else None
    combined = None
    if final:
        combined = {**final['observation'], 'durationMs': sum(a['durationMs'] for a in completed),
                    'tokens': _combined_tokens(observations)}
    summary = [{'configuration': a['configuration'], 'reason': a['reason'], 'status': a['observation']['status'],
                'durationMs': a['durationMs'], 'tokens': a['observation']['tokens'],
                'failures': a['observation']['failures']} for a in completed]
    decision = {'schemaVersion': 4, 'requestId': instance, 'sequenceIndex': index+1, **selection,
                'status': final['observation']['status'] if final else 'unserved',
                'tokens': combined['tokens'] if combined else None,
                'durationMs': combined['durationMs'] if combined else None,
                'delayRequestedMs': sum(a['delayRequestedMs'] for a in completed),
                'delayActualMs': sum(a['delayActualMs'] for a in completed),
                'toolDelayRequestedMs': sum(a['toolDelayRequestedMs'] for a in completed),
                'toolDelayActualMs': sum(a['toolDelayActualMs'] for a in completed),
                'toolCallsDelayed': sum(a['toolCallsDelayed'] for a in completed),
                'attempts': summary, 'finalConfiguration': final['configuration'] if final else None,
                'fallbackReason': completed[0]['observation']['failures'] if len(completed) > 1 else None,
                'ledger': controller.ledger()}
    packet.update(state='completed', trial=final['trial'] if final else None,
                  result=final['result'] if final else None, observation=combined, decision=decision,
                  ledger=controller.ledger(), completedAt=datetime.now(timezone.utc).isoformat(),
                  timing={'schemaVersion': 3, 'sequenceIndex': index+1,
                          'durationMs': combined['durationMs'] if combined else None})
    sealed_write(packet_path, packet)
    checkpoint('outcome_saved', index+1)
    return packet


def classify_failures(result, thrown=None):
    evidence = []
    if any(call.get('isError') is True for call in result.trace.toolCalls):
        evidence.append('operation')
    if result.status != 'success':
        message = result.errorMessage or ''
        metadata = next((event.get('metadata', {}) for event in result.trace.aiTrace.get('events', [])
                         if event.get('type') == 'error' and event.get('metadata', {}).get('exceptionType')), {})
        module = metadata.get('exceptionModule', '')
        kind = metadata.get('exceptionType', '')
        if 'exceeded max_steps=' in message:
            evidence.append('step-limit')
        elif (isinstance(thrown, McpError) or module.startswith(('mcp', 'fastmcp')) or
              ((isinstance(thrown, (ConnectionError, TimeoutError)) or kind in ('ConnectionError', 'TimeoutError'))
               and getattr(result, 'strategy', None) == 'local_mcp')):
            evidence.append('transport')
        elif (thrown is not None and thrown.__class__.__module__.startswith(('openai', 'anthropic', 'google.genai'))
              or module.startswith(('openai', 'anthropic', 'google.genai'))):
            evidence.append('provider')
        elif (isinstance(thrown, KeyError) or kind == 'KeyError') and getattr(result, 'strategy', None) in ('local_mcp', 'local_function'):
            evidence.append('tool-use')
        else:
            evidence.append('unknown')
    return evidence
