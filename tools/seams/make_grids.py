"""Write the SEAMS v2 replay grids and study definitions from one place.

Policies and scenario parameters are defined here once, so replay grids, pilots and
live study definitions cannot drift apart. Re-run after editing; outputs are
deterministic JSON under examples/studies/.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'examples' / 'studies'
BASELINE = '../../baselines/repoqa-long64-v2/frozen.json'

INLINE, MCP, MCP_LEAN = 'inline-code-full', 'local-mcp-default', 'local-mcp-lean'
FN, FN_LEAN = 'local-function-default', 'local-function-lean'
BINS = ('small', 'medium', 'large')

# Provisional v2 router: selected by replay on v1 calibration (round-robin probes every
# 10 requests, 12-request estimate TTL). Re-select on v2 calibration before collection.
V2 = {'type': 'router', 'adaptive': True, 'estimator': 'pooled-ratio', 'incumbentScope': 'bin',
      'latencyQuantile': 0.9, 'switchOnObjectiveMiss': True, 'cooldownRequests': 2,
      'updateWindow': 4, 'minimumObservations': 2, 'probeInterval': 10, 'estimateTtlRequests': 12}
V1 = {'type': 'router', 'adaptive': True}
FROZEN = {'type': 'router', 'adaptive': False, 'incumbentScope': 'bin', 'latencyQuantile': 0.9}
V2_CANDIDATES = {
    'v2-rr10-ttl12': {},
    'v2-rr10-ttl8': {'estimateTtlRequests': 8},
    'v2-t8-ttl8': {'probeMode': 'targeted', 'avoidedProbeInterval': 8, 'estimateTtlRequests': 8},
    'v2-t10-ttl10': {'probeMode': 'targeted', 'avoidedProbeInterval': 10, 'estimateTtlRequests': 10},
}
ABLATIONS = {
    'per-bin-mean': {'estimator': 'per-bin-mean'}, 'no-ttl': {'estimateTtlRequests': None},
    'mean-routing': {'latencyQuantile': None}, 'global-scope': {'incumbentScope': 'global'},
    'no-objective-first': {'switchOnObjectiveMiss': False}, 'cooldown-5': {'cooldownRequests': 5},
    'targeted-every-2': {'probeMode': 'targeted', 'avoidedProbeInterval': 2},
}

# S-A: MCP tool-call delay during requests 31-60 of 96; inline is the feasible fallback.
# The original pair (inline + MCP default, limits 8-12 s) is kept as a replay grid: on v2
# calibration MCP default drifted to p90 13-14 s and the pre-registered rule found no opportunity.
SA_LIMIT_MS, SA_DELAY_MS, SA_FIRST, SA_LAST = 10000, 2000, 31, 60
NORMAL_ROUTE = {'small': INLINE, 'medium': MCP, 'large': MCP}

# Amended S-A (deviation recorded in the pre-registration): the cheap configuration is lean.
# Function runtimes support only request-scope delay; about 3 tool calls per request in v2
# calibration, so 6000/9000 ms per request matches 2000/3000 ms per tool call.
SA_LIMITS = (12000, 14000, 16000)
SA_PAIRS = {
    'mcp-lean': {'cheap': MCP_LEAN, 'scope': 'tool-call', 'delays': (2000, 3000), 'scenario': 'mcp-lean-degraded'},
    'fn-lean': {'cheap': FN_LEAN, 'scope': 'request', 'delays': (6000, 9000), 'scenario': 'function-lean-degraded'},
}
# Live parameters per pair, from select_parameters.py records on v2 calibration. fn-lean failed
# the stationary cost constraint (rule fails closed) and is a replay-only negative case.
SA_SELECTED = {'mcp-lean': {'latencyLimitMs': 14000, 'delayMs': 3000, 'policy': 'v2-rr10-ttl8'}}


# S-E: inline is the incumbent (lean infeasible at its calibration p90) and degrades by a
# request-scope delay during requests 31-60; lean is the cheaper, slower fallback.
SE_LIMITS, SE_DELAYS = (9000, 10000, 11000), (3000, 6000, 9000)
SE_SELECTED = {'latencyLimitMs': 10000, 'delayMs': 9000, 'policy': 'v2-t10-ttl10'}
ALL_INLINE, ALL_LEAN = dict.fromkeys(BINS, INLINE), dict.fromkeys(BINS, MCP_LEAN)


def variant(base, change):
    return {k: v for k, v in {**base, **change}.items() if v is not None}


def mcp_delay(first, last, delay=None):
    return {'kind': 'delay', 'configuration': MCP, 'scope': 'tool-call', 'delayMs': delay or SA_DELAY_MS,
            'firstRequest': first, 'lastRequest': last}


def delay_effect(pair, first, last, delay):
    spec = SA_PAIRS[pair]
    return {'kind': 'delay', 'configuration': spec['cheap'], 'scope': spec['scope'], 'delayMs': delay,
            'firstRequest': first, 'lastRequest': last}


def route(pair):
    cheap = SA_PAIRS[pair]['cheap']
    return {'small': INLINE, 'medium': cheap, 'large': cheap}


def oracle(first, last, during, default=NORMAL_ROUTE):
    return {'type': 'schedule', 'default': default,
            'phases': [{'firstRequest': first, 'lastRequest': last, 'configurationBySize': during}]}


def degradation_grid():
    policies = {'inline': {'type': 'fixed', 'configuration': INLINE}, 'mcp': {'type': 'fixed', 'configuration': MCP},
                'frozen': FROZEN, 'v1': V1}
    policies.update({name: variant(V2, change) for name, change in V2_CANDIDATES.items()})
    policies.update({f'v2-{name}': variant(V2, change) for name, change in ABLATIONS.items()})
    points = [{'name': f'stationary-L{limit}', 'latencyLimitMs': limit, 'effects': [],
               'policies': {'oracle': {'type': 'schedule', 'default': NORMAL_ROUTE}}} for limit in (8000, 10000, 12000)]
    for limit in (8000, 10000, 12000):
        for delay in (1000, 2000, 3000):
            for duration in (12, 24, 30, 36):
                first, last = SA_FIRST, SA_FIRST+duration-1
                points.append({'name': f'L{limit}-d{delay}-n{duration}', 'latencyLimitMs': limit,
                               'effects': [mcp_delay(first, last, delay)],
                               'policies': {'oracle': oracle(first, last, dict.fromkeys(BINS, INLINE))}})
    return {'schemaVersion': 1, 'seeds': [201, 202, 203], 'replicates': 10, 'configurations': [INLINE, MCP],
            'base': {}, 'policies': policies, 'points': points}


def pair_grid(pair):
    cheap = SA_PAIRS[pair]['cheap']
    policies = {'inline': {'type': 'fixed', 'configuration': INLINE}, 'cheap': {'type': 'fixed', 'configuration': cheap},
                'frozen': FROZEN, 'v1': V1}
    policies.update({name: variant(V2, change) for name, change in V2_CANDIDATES.items()})
    policies.update({f'v2-{name}': variant(V2, change) for name, change in ABLATIONS.items()})
    points = [{'name': f'stationary-L{limit}', 'latencyLimitMs': limit, 'effects': [],
               'policies': {'oracle': {'type': 'schedule', 'default': route(pair)}}} for limit in SA_LIMITS]
    for limit in SA_LIMITS:
        for delay in SA_PAIRS[pair]['delays']:
            for duration in (12, 24, 30, 36):
                first, last = SA_FIRST, SA_FIRST+duration-1
                points.append({'name': f'L{limit}-d{delay}-n{duration}', 'latencyLimitMs': limit,
                               'effects': [delay_effect(pair, first, last, delay)],
                               'policies': {'oracle': oracle(first, last, dict.fromkeys(BINS, INLINE), route(pair))}})
    return {'schemaVersion': 1, 'seeds': [201, 202, 203], 'replicates': 10, 'configurations': [INLINE, cheap],
            'base': {}, 'policies': policies, 'points': points}


def inline_delay(first, last, delay):
    return {'kind': 'delay', 'configuration': INLINE, 'scope': 'request', 'delayMs': delay,
            'firstRequest': first, 'lastRequest': last}


def inline_degradation_grid():
    policies = {'inline': {'type': 'fixed', 'configuration': INLINE}, 'cheap': {'type': 'fixed', 'configuration': MCP_LEAN},
                'frozen': FROZEN, 'v1': V1}
    policies.update({name: variant(V2, change) for name, change in V2_CANDIDATES.items()})
    policies.update({f'v2-{name}': variant(V2, change) for name, change in ABLATIONS.items()})
    points = [{'name': f'stationary-L{limit}', 'latencyLimitMs': limit, 'effects': [],
               'policies': {'oracle': {'type': 'schedule', 'default': ALL_INLINE}}} for limit in SE_LIMITS]
    for limit in SE_LIMITS:
        for delay in SE_DELAYS:
            for duration in (12, 24, 30, 36):
                first, last = SA_FIRST, SA_FIRST+duration-1
                points.append({'name': f'L{limit}-d{delay}-n{duration}', 'latencyLimitMs': limit,
                               'effects': [inline_delay(first, last, delay)],
                               'policies': {'oracle': oracle(first, last, ALL_LEAN, ALL_INLINE)}})
    return {'schemaVersion': 1, 'seeds': [201, 202, 203], 'replicates': 10, 'configurations': [INLINE, MCP_LEAN],
            'base': {}, 'policies': policies, 'points': points}


def opposing_grid():
    policies = {'inline': {'type': 'fixed', 'configuration': INLINE}, 'mcp': {'type': 'fixed', 'configuration': MCP},
                'frozen': FROZEN, 'v1': V1, 'v2': V2}
    points = []
    for quota in (30000, 60000, 120000, 250000):
        points.append({'name': f'L{SA_LIMIT_MS}-q{quota//1000}k', 'latencyLimitMs': SA_LIMIT_MS,
            'effects': [mcp_delay(25, 48), {'kind': 'token-quota', 'tokensPerMinute': quota,
                                             'firstRequest': 49, 'lastRequest': 72}],
            'policies': {'oracle': {'type': 'schedule', 'default': NORMAL_ROUTE, 'phases': [
                {'firstRequest': 25, 'lastRequest': 48, 'configurationBySize': dict.fromkeys(BINS, INLINE)},
                {'firstRequest': 49, 'lastRequest': 72, 'configurationBySize': dict.fromkeys(BINS, MCP)}]}}})
    return {'schemaVersion': 1, 'seeds': [201, 202, 203], 'replicates': 10, 'configurations': [INLINE, MCP],
            'base': {}, 'policies': policies, 'points': points}


def transport_grid():
    policies = {'mcp': {'type': 'fixed', 'configuration': MCP}, 'function': {'type': 'fixed', 'configuration': FN},
                'frozen': FROZEN, 'v2': V2,
                'cascade': {'type': 'cascade', 'primary': MCP, 'fallbacks': [FN],
                            'triggerFailureClasses': ['step-limit', 'tool-use', 'transport']}}
    points = [{'name': f'fault{int(rate*100)}', 'latencyLimitMs': SA_LIMIT_MS,
               'effects': [{'kind': 'fault', 'configuration': MCP, 'toolErrorRate': rate, 'seed': 11,
                            'firstRequest': SA_FIRST, 'lastRequest': SA_LAST}],
               'policies': {'oracle': oracle(SA_FIRST, SA_LAST, dict.fromkeys(BINS, FN), dict.fromkeys(BINS, MCP))}}
              for rate in (0.3, 0.5, 0.7)]
    return {'schemaVersion': 1, 'seeds': [201, 202, 203], 'replicates': 10, 'configurations': [MCP, FN],
            'base': {}, 'policies': policies, 'points': points}


def cascade_policies():
    return {'inline': {'type': 'fixed', 'configuration': INLINE},
            'mcp-default': {'type': 'fixed', 'configuration': MCP},
            'mcp-lean': {'type': 'fixed', 'configuration': MCP_LEAN},
            'function-default': {'type': 'fixed', 'configuration': FN},
            'function-lean': {'type': 'fixed', 'configuration': FN_LEAN},
            'cascade-mcp': {'type': 'cascade', 'primary': MCP_LEAN, 'fallbacks': [MCP]},
            'cascade-mcp-inline': {'type': 'cascade', 'primary': MCP_LEAN, 'fallbacks': [INLINE]},
            'cascade-fn': {'type': 'cascade', 'primary': FN_LEAN, 'fallbacks': [FN]}}


def study_cascade():
    return {'schemaVersion': 1, 'baseline': BASELINE, 'configurations': [INLINE, MCP, MCP_LEAN, FN, FN_LEAN],
            'seeds': [301, 302, 303], 'repeats': 1, 'policies': cascade_policies(),
            'scenarios': {'stationary': []},
            'comparisons': [['cascade-mcp', 'mcp-default'], ['cascade-mcp', 'mcp-lean'], ['cascade-mcp', 'inline'],
                            ['cascade-mcp-inline', 'inline'], ['cascade-fn', 'function-default'],
                            ['mcp-lean', 'function-lean']]}


def study_degradation(pair='mcp-lean'):
    spec, chosen = SA_PAIRS[pair], SA_SELECTED[pair]
    v2 = variant(V2, V2_CANDIDATES[chosen['policy']])
    return {'schemaVersion': 1, 'baseline': BASELINE, 'configurations': [INLINE, spec['cheap']],
            'seeds': [301, 302, 303], 'repeats': 1, 'latencyLimitMs': chosen['latencyLimitMs'],
            'policies': {'inline': {'type': 'fixed', 'configuration': INLINE},
                         'cheap': {'type': 'fixed', 'configuration': spec['cheap']},
                         'frozen': FROZEN, 'v1': V1, 'v2': v2,
                         'oracle': oracle(SA_FIRST, SA_LAST, dict.fromkeys(BINS, INLINE), route(pair))},
            'scenarios': {'stationary': [],
                          spec['scenario']: [delay_effect(pair, SA_FIRST, SA_LAST, chosen['delayMs'])]},
            'comparisons': [['v2', 'frozen'], ['v2', 'v1'], ['v2', 'inline'], ['v2', 'oracle'], ['v1', 'frozen']]}


PILOT_DEGRADATION_TARGETS = ['java_002', 'java_003', 'py_002', 'py_003', 'rs_001', 'rs_002', 'ts_003', 'ts_004']


def pilot_cascade():
    policies = cascade_policies()
    return {'schemaVersion': 1, 'baseline': BASELINE, 'configurations': [INLINE, MCP, MCP_LEAN, FN, FN_LEAN],
            'targets': ['rs_004', 'py_005', 'java_002', 'ts_001'], 'seeds': [901], 'repeats': 1,
            'policies': {k: policies[k] for k in ('mcp-lean', 'mcp-default', 'function-lean', 'cascade-mcp')},
            'scenarios': {'stationary': []}, 'comparisons': [['cascade-mcp', 'mcp-default']]}


def pilot_degradation(pair='mcp-lean'):
    spec, chosen = SA_PAIRS[pair], SA_SELECTED[pair]
    return {'schemaVersion': 1, 'baseline': BASELINE, 'configurations': [INLINE, spec['cheap']],
            'targets': PILOT_DEGRADATION_TARGETS, 'seeds': [902], 'repeats': 1,
            'latencyLimitMs': chosen['latencyLimitMs'],
            'policies': {'cheap': {'type': 'fixed', 'configuration': spec['cheap']}, 'frozen': FROZEN, 'v1': V1,
                         'v2': variant(V2, V2_CANDIDATES[chosen['policy']])},
            'scenarios': {spec['scenario']: [delay_effect(pair, 17, 32, chosen['delayMs'])]},
            'comparisons': [['v2', 'frozen']]}


def study_inline_degradation():
    chosen = SE_SELECTED
    return {'schemaVersion': 1, 'baseline': BASELINE, 'configurations': [INLINE, MCP_LEAN],
            'seeds': [301, 302, 303], 'repeats': 1, 'latencyLimitMs': chosen['latencyLimitMs'],
            'policies': {'inline': {'type': 'fixed', 'configuration': INLINE},
                         'cheap': {'type': 'fixed', 'configuration': MCP_LEAN},
                         'frozen': FROZEN, 'v1': V1, 'v2': variant(V2, V2_CANDIDATES[chosen['policy']]),
                         'oracle': oracle(SA_FIRST, SA_LAST, ALL_LEAN, ALL_INLINE)},
            'scenarios': {'stationary': [], 'inline-degraded': [inline_delay(SA_FIRST, SA_LAST, chosen['delayMs'])]},
            'comparisons': [['v2', 'frozen'], ['v2', 'v1'], ['v2', 'cheap'], ['v2', 'inline'], ['v2', 'oracle'],
                            ['v1', 'frozen']]}


def pilot_inline_degradation():
    chosen = SE_SELECTED
    return {'schemaVersion': 1, 'baseline': BASELINE, 'configurations': [INLINE, MCP_LEAN],
            'targets': PILOT_DEGRADATION_TARGETS, 'seeds': [903], 'repeats': 1,
            'latencyLimitMs': chosen['latencyLimitMs'],
            'policies': {'inline': {'type': 'fixed', 'configuration': INLINE}, 'frozen': FROZEN, 'v1': V1,
                         'v2': variant(V2, V2_CANDIDATES[chosen['policy']])},
            'scenarios': {'inline-degraded': [inline_delay(17, 32, chosen['delayMs'])]},
            'comparisons': [['v2', 'frozen']]}


# v3 catalogue (pre-registration, "v3 scenarios and selection rules"): the direct surface
# is fast and cheap, so the incumbent depends on the limit.
MCP_DIRECT = 'local-mcp-direct'
ALL_DIRECT = dict.fromkeys(BINS, MCP_DIRECT)
V3_GRIDS = {
    'inline-degradation': {'configurations': [INLINE, MCP_DIRECT], 'limits': (6000, 7000, 8000)},
    'direct-degradation': {'configurations': [INLINE, MCP_DIRECT, MCP_LEAN], 'limits': (8000, 10000, 12000)},
    'quota': {'configurations': [INLINE, MCP_DIRECT], 'limits': (6000, 7000, 8000)},
    'round-trip': {'configurations': [INLINE, MCP_DIRECT, MCP_LEAN], 'limits': (8000, 10000)},
}
V3_DURATIONS = (12, 24, 30, 36)


def tool_delay(configuration, first, last, delay):
    return {'kind': 'delay', 'configuration': configuration, 'scope': 'tool-call', 'delayMs': delay,
            'firstRequest': first, 'lastRequest': last}


def v3_disturbances(name, first, last):
    """(label, effects, oracle schedules during the disturbance, default route) per magnitude."""
    if name == 'inline-degradation':
        for delay in (3000, 6000, 9000):
            yield f'd{delay}', [inline_delay(first, last, delay)], {'oracle': ALL_DIRECT}, ALL_INLINE
    elif name == 'direct-degradation':
        for delay in (1000, 2000, 3000):
            yield (f'd{delay}', [tool_delay(MCP_DIRECT, first, last, delay)],
                   {'oracle': ALL_INLINE, 'oracle-lean': ALL_LEAN}, ALL_DIRECT)
    elif name == 'quota':
        for quota in (40000, 60000, 100000, 150000):
            yield (f'q{quota//1000}k', [{'kind': 'token-quota', 'tokensPerMinute': quota,
                                         'firstRequest': first, 'lastRequest': last}],
                   {'oracle': ALL_DIRECT, 'oracle-split': {'small': INLINE, 'medium': MCP_DIRECT, 'large': MCP_DIRECT}},
                   ALL_INLINE)
    elif name == 'round-trip':
        for delay in (1000, 2000, 3000):
            yield (f'd{delay}', [tool_delay(MCP_DIRECT, first, last, delay), tool_delay(MCP_LEAN, first, last, delay)],
                   {'oracle': ALL_INLINE}, ALL_DIRECT)


def v3_grid(name):
    spec = V3_GRIDS[name]
    configurations = spec['configurations']
    policies = {('inline' if c == INLINE else c.removeprefix('local-mcp-')): {'type': 'fixed', 'configuration': c}
                for c in configurations}
    policies.update({'frozen': FROZEN, 'v1': V1})
    policies.update({name: variant(V2, change) for name, change in V2_CANDIDATES.items()})
    policies.update({f'v2-{name}': variant(V2, change) for name, change in ABLATIONS.items()})
    default = next(v3_disturbances(name, SA_FIRST, SA_LAST))[3]
    points = [{'name': f'stationary-L{limit}', 'latencyLimitMs': limit, 'effects': [],
               'policies': {'oracle': {'type': 'schedule', 'default': default}}} for limit in spec['limits']]
    for limit in spec['limits']:
        for duration in V3_DURATIONS:
            first, last = SA_FIRST, SA_FIRST+duration-1
            for label, effects, oracles, default in v3_disturbances(name, first, last):
                points.append({'name': f'L{limit}-{label}-n{duration}', 'latencyLimitMs': limit, 'effects': effects,
                               'policies': {key: oracle(first, last, during, default) for key, during in oracles.items()}})
    return {'schemaVersion': 1, 'seeds': [201, 202, 203], 'replicates': 10, 'configurations': configurations,
            'base': {}, 'policies': policies, 'points': points}


# S-E' live (pre-registration, "Outcome of the v3 selection"): selection record
# studies/replay-v3calib/selection-inline.json; seeds 301-305 by decision before the pilot.
BASELINE_V3 = '../../baselines/repoqa-long64-v3/frozen.json'
SE3_SELECTED = {'latencyLimitMs': 7000, 'delayMs': 9000, 'policy': 'v2-t10-ttl10'}


def study_v3_inline_degradation():
    chosen = SE3_SELECTED
    return {'schemaVersion': 1, 'baseline': BASELINE_V3, 'configurations': [INLINE, MCP_DIRECT],
            'seeds': [301, 302, 303, 304, 305], 'repeats': 1, 'latencyLimitMs': chosen['latencyLimitMs'],
            'policies': {'inline': {'type': 'fixed', 'configuration': INLINE},
                         'direct': {'type': 'fixed', 'configuration': MCP_DIRECT},
                         'frozen': FROZEN, 'v1': V1, 'v2': variant(V2, V2_CANDIDATES[chosen['policy']]),
                         'oracle': oracle(SA_FIRST, SA_LAST, ALL_DIRECT, ALL_INLINE)},
            'scenarios': {'stationary': [], 'inline-degraded': [inline_delay(SA_FIRST, SA_LAST, chosen['delayMs'])]},
            'comparisons': [['v2', 'frozen'], ['v2', 'v1'], ['v2', 'direct'], ['v2', 'inline'], ['v2', 'oracle'],
                            ['v1', 'frozen']]}


# Limit sweep (exploratory, after S-E' collection): how narrow the window for adaptation is.
# The S-E' disturbance and arms at limits 5-10 s; replay only, labelled estimated.
SWEEP_LIMITS = tuple(range(5000, 10001, 500))


def limit_sweep_grid():
    chosen = SE3_SELECTED
    effects = [inline_delay(SA_FIRST, SA_LAST, chosen['delayMs'])]
    points = []
    for limit in SWEEP_LIMITS:
        points.append({'name': f'stationary-L{limit}', 'latencyLimitMs': limit, 'effects': [],
                       'policies': {'oracle': {'type': 'schedule', 'default': ALL_INLINE}}})
        points.append({'name': f'L{limit}-d{chosen["delayMs"]}-n30', 'latencyLimitMs': limit, 'effects': effects,
                       'policies': {'oracle': oracle(SA_FIRST, SA_LAST, ALL_DIRECT, ALL_INLINE)}})
    return {'schemaVersion': 1, 'seeds': [201, 202, 203], 'replicates': 10, 'configurations': [INLINE, MCP_DIRECT],
            'base': {}, 'policies': {'inline': {'type': 'fixed', 'configuration': INLINE},
                                     'direct': {'type': 'fixed', 'configuration': MCP_DIRECT},
                                     'frozen': FROZEN, 'v1': V1, 'v2': variant(V2, V2_CANDIDATES[chosen['policy']])},
            'points': points}


def pilot_v3_inline_degradation():
    chosen = SE3_SELECTED
    return {'schemaVersion': 1, 'baseline': BASELINE_V3, 'configurations': [INLINE, MCP_DIRECT],
            'targets': PILOT_DEGRADATION_TARGETS, 'seeds': [904], 'repeats': 1,
            'latencyLimitMs': chosen['latencyLimitMs'],
            'policies': {'inline': {'type': 'fixed', 'configuration': INLINE}, 'frozen': FROZEN, 'v1': V1,
                         'v2': variant(V2, V2_CANDIDATES[chosen['policy']])},
            'scenarios': {'inline-degraded': [inline_delay(17, 32, chosen['delayMs'])]},
            'comparisons': [['v2', 'frozen']]}


OUTPUTS = {
    **{f'replay/v3-{name}.grid.json': (lambda name=name: v3_grid(name)) for name in V3_GRIDS},
    'replay/v3-limit-sweep.grid.json': limit_sweep_grid,
    'study.seams3-inline-degradation.json': study_v3_inline_degradation,
    'pilot.v3-inline-degradation.json': pilot_v3_inline_degradation,
    'replay/degradation.grid.json': degradation_grid, 'replay/opposing.grid.json': opposing_grid,
    'replay/transport.grid.json': transport_grid,
    'replay/degradation-mcp-lean.grid.json': lambda: pair_grid('mcp-lean'),
    'replay/degradation-fn-lean.grid.json': lambda: pair_grid('fn-lean'),
    'replay/inline-degradation.grid.json': inline_degradation_grid,
    'study.seams-cascade.json': study_cascade,
    'study.seams-degradation.json': lambda: study_degradation('mcp-lean'),
    'pilot.cascade.json': pilot_cascade,
    'pilot.degradation.json': lambda: pilot_degradation('mcp-lean'),
    'study.seams-inline-degradation.json': study_inline_degradation,
    'pilot.inline-degradation.json': pilot_inline_degradation,
}


def apply_selection(item):
    """Use a select_parameters.py record (`pair=path`; `inline` for S-E) for the live definitions."""
    pair, path = item.split('=', 1)
    if pair == 'inline':
        decision = json.loads(Path(path).read_text())['decision']
        SE_SELECTED.update({k: decision[k] for k in ('latencyLimitMs', 'delayMs', 'policy')})
        return
    if pair not in SA_PAIRS:
        raise SystemExit(f'unknown S-A pair {pair!r}; expected one of {sorted(SA_PAIRS)}')
    decision = json.loads(Path(path).read_text())['decision']
    SA_SELECTED[pair] = {k: decision[k] for k in ('latencyLimitMs', 'delayMs', 'policy')}


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Generate SEAMS v2 replay grids and study definitions.')
    parser.add_argument('--selection', action='append', default=[], metavar='PAIR=RECORD',
                        help='Selection record from tools/seams/select_parameters.py for an S-A pair (repeatable)')
    args = parser.parse_args()
    for item in args.selection:
        apply_selection(item)
    for name, build in OUTPUTS.items():
        payload = build()
        path = OUT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + '\n')
        print(path.relative_to(ROOT))
    return


if __name__ == '__main__':
    main()
