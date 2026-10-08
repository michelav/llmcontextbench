"""Controlled disturbances and frozen calibration; no provider access."""
from __future__ import annotations

from math import ceil, isfinite
from time import sleep

from .types import EstimateKey, Observation, SizeBin, Provenance, TokenUsage, estimate_from_observations

DELAYS_MS = (100, 250, 500, 1000)


class DelayedRuntime:
    def __init__(self, runtime, delay_ms, sleeper=sleep):
        if not isfinite(delay_ms) or delay_ms < 0:
            raise ValueError('delay must be finite and nonnegative')
        self.runtime, self.delay_ms, self.sleeper = runtime, delay_ms, sleeper

    def list_tools(self):
        return self.runtime.list_tools()

    def call_tool(self, name, arguments):
        self.sleeper(self.delay_ms / 1000)
        return self.runtime.call_tool(name, arguments)

    def close(self):
        self.runtime.close()


def delay_at(index, scenario, delay_ms):
    if index < 1 or scenario not in ('stationary', 'degradation-recovery'):
        raise ValueError('invalid disturbance schedule')
    return delay_ms if scenario == 'degradation-recovery' and 21 <= index <= 44 else 0


def quantile(values, probability):
    """Nearest-rank quantile, deterministic and recorded in frozen metadata."""
    if not values or not 0 < probability <= 1 or any(not isfinite(v) or v < 0 for v in values):
        raise ValueError('quantile requires finite nonnegative observations')
    return sorted(values)[max(0, ceil(probability * len(values)) - 1)]


def observations_from_packets(packets):
    return [Observation(o['configuration_id'], SizeBin(o['size_bin']), o['status'],
                        o['end_to_end_duration_ms'], TokenUsage(o['tokens']['value'], Provenance(o['tokens']['provenance'])),
                        Provenance(o['duration_provenance']))
            for p in packets if (o := p['observation']) is not None]


def freeze_calibration(baseline, delays, *, prepared_hash, application_slo_ms=None):
    from ctxbench.adapters.repoqa.study import digest
    observations = observations_from_packets(baseline)
    if len(observations) != 64:
        raise ValueError('baseline must contain exactly 64 executions')
    if any(not o.valid or o.end_to_end_duration_ms is None for o in observations):
        raise ValueError('successful measured baseline required before freezing')
    if application_slo_ms is not None and (not isfinite(application_slo_ms) or application_slo_ms < 0):
        raise ValueError('invalid application SLO')
    groups = {}
    for o in observations:
        groups.setdefault(EstimateKey(o.configuration_id, o.size_bin), []).append(o)
    if len(groups) != 4 or any(len(v) != 16 for v in groups.values()):
        raise ValueError('baseline must balance configuration and size bin')
    objective = application_slo_ms if application_slo_ms is not None else quantile([o.end_to_end_duration_ms for o in observations], .9)
    local = [o.end_to_end_duration_ms for o in observations if o.configuration_id == 'local-mcp-repoqa-ops']
    baseline_p95 = quantile(local, .95)
    qualifications = {}
    for delay in DELAYS_MS:
        delayed = observations_from_packets(delays.get(delay, []))
        values = [o.end_to_end_duration_ms for o in delayed if o.valid and o.end_to_end_duration_ms is not None]
        complete = len(delayed) == 32 and len(values) == 32 and all(o.configuration_id == 'local-mcp-repoqa-ops' for o in delayed)
        p95 = quantile(values, .95) if complete else None
        qualifications[str(delay)] = {'complete': complete, 'p95Ms': p95,
                                      'qualifies': bool(complete and p95 >= baseline_p95 * 1.25
                                                        and any(v > objective for v in values))}
    chosen = next((d for d in DELAYS_MS if qualifications[str(d)]['qualifies']), None)
    from dataclasses import asdict
    estimates = [{'key': asdict(k), 'estimate': asdict(estimate_from_observations(v))} for k, v in groups.items()]
    return {'schemaVersion': 1, 'preparedHash': prepared_hash, 'baselineHash': digest(baseline),
            'delayHashes': {str(d): digest(delays.get(d, [])) for d in DELAYS_MS},
            'quantileMethod': 'nearest-rank', 'objectiveSource': 'application-slo' if application_slo_ms is not None else 'pooled-baseline-p90',
            'latencyObjectiveMs': objective, 'baselineLocalP95Ms': baseline_p95, 'selectedDelayMs': chosen,
            'scenarios': ['stationary', 'degradation-recovery'] if chosen else ['stationary'],
            'qualification': qualifications, 'estimates': estimates}


def load_estimates(frozen):
    from .types import Estimate, PerformanceEstimate
    def metric(row):
        return Estimate(row['value'], Provenance(row['provenance']), row['observation_count'],
                        tuple(Provenance(p) for p in row['source_provenance']))
    return {EstimateKey(r['key']['configuration_id'], SizeBin(r['key']['size_bin'])):
            PerformanceEstimate(metric(r['estimate']['latency_ms']), metric(r['estimate']['total_tokens']))
            for r in frozen['estimates']}
