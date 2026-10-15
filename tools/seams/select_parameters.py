"""Apply the pre-registered S-A selection rule to a degradation replay report.

Rule (docs/development/seams2027-preregistration.md):
1. Among `n30` points with the given limits and delays (originally 10000/12000 ms and
   2000/3000 ms; amended per S-A pair after v2 calibration drift), choose the largest
   frozen − oracle miss gap; ties go to the smaller delay. A non-positive gap fails closed.
   Amended rule (`--feasible-config`): the limit is not searched; it is the smallest given
   limit at or above the configuration's largest per-bin calibration p90 latency (C3).
2. Among the candidate v2 policies, choose the fewest mean misses at that point,
   subject to stationary misses ≤ frozen + 1 per episode and stationary tokens
   ≤ 1.15 × frozen at the same limit; ties go to the lower recovery lag.
The output records the inputs, digest and decision so the choice can be audited.
"""
import argparse
import hashlib
import json
from pathlib import Path

CANDIDATES = ('v2-rr10-ttl12', 'v2-rr10-ttl8', 'v2-t8-ttl8', 'v2-t10-ttl10')
LIMITS, DELAYS, DURATION = (10000, 12000), (2000, 3000), 30
RULE = 'seams2027-preregistration S-A v1'


def calibration_p90(baseline, configuration):
    rows = json.loads(Path(baseline).read_text())['payload']['observations']
    p90 = {}
    for size in {r['sizeBin'] for r in rows}:
        values = sorted(r['durationMs'] for r in rows if r['configuration'] == configuration and r['sizeBin'] == size)
        p90[size] = values[min(len(values)-1, int(0.9*len(values)))]
    return {k: round(v) for k, v in sorted(p90.items())}


def feasible_limit(baseline, configuration, limits):
    p90 = calibration_p90(baseline, configuration)
    feasible = [limit for limit in sorted(limits) if limit >= max(p90.values())]
    if not feasible:
        raise SystemExit(f'no limit covers the calibration p90 of {configuration} ({max(p90.values()):.0f} ms)')
    return feasible[0], p90


def infeasible_limit(baseline, configuration, limits):
    p90 = calibration_p90(baseline, configuration)
    below = [limit for limit in sorted(limits) if limit < min(p90.values())]
    if not below:
        raise SystemExit(f'every limit admits {configuration} at its calibration p90 ({min(p90.values()):.0f} ms)')
    return below[-1], p90


def select(report, limits=LIMITS, delays=DELAYS):
    points = {p['name']: p for p in report['points']}
    eligible_points = [points[f'L{limit}-d{delay}-n{DURATION}'] for limit in limits for delay in delays]
    chosen = max(eligible_points, key=lambda p: (p['opportunity'], -p['effects'][0]['delayMs']))
    if chosen['opportunity'] <= 0:
        raise SystemExit(f"largest opportunity is {chosen['opportunity']:.2f} at {chosen['name']}; the rule fails closed")
    limit = chosen['latencyLimitMs']
    stationary = points[f'stationary-L{limit}']['policies']
    frozen = stationary['frozen']
    admissible = [c for c in CANDIDATES
                  if stationary[c]['deadlineMisses'] <= frozen['deadlineMisses'] + 1
                  and stationary[c]['tokensLowerBound'] <= 1.15 * frozen['tokensLowerBound']]
    if not admissible:
        raise SystemExit('no candidate satisfies the stationary constraints; the rule fails closed')
    policies = chosen['policies']
    def lag(name):
        value = policies[name]['recoveryLag']
        return float('inf') if value is None else value
    policy = min(admissible, key=lambda c: (policies[c]['deadlineMisses'], lag(c)))
    return {'point': chosen['name'], 'latencyLimitMs': limit, 'delayMs': chosen['effects'][0]['delayMs'],
            'opportunity': chosen['opportunity'], 'policy': policy, 'admissible': admissible,
            'pointMisses': {c: policies[c]['deadlineMisses'] for c in CANDIDATES},
            'frozenMisses': policies['frozen']['deadlineMisses'], 'oracleMisses': policies['oracle']['deadlineMisses']}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('report', help='Replay report produced from examples/studies/replay/degradation.grid.json')
    parser.add_argument('--output', required=True)
    parser.add_argument('--limits', default=','.join(map(str, LIMITS)), help='Comma-separated latency limits (ms)')
    parser.add_argument('--delays', default=','.join(map(str, DELAYS)), help='Comma-separated delays (ms)')
    parser.add_argument('--rule', default=RULE, help='Rule label recorded with the decision')
    parser.add_argument('--feasible-config', help='Fix the limit from this configuration\'s calibration p90')
    parser.add_argument('--infeasible-config', help='Fix the limit below this configuration\'s calibration p90 (S-E)')
    parser.add_argument('--baseline', help='Frozen baseline used with --feasible-config/--infeasible-config')
    args = parser.parse_args()
    limits, delays = (tuple(int(v) for v in arg.split(',')) for arg in (args.limits, args.delays))
    feasibility = None
    if (args.feasible_config or args.infeasible_config) and not args.baseline:
        parser.error('--feasible-config/--infeasible-config require --baseline')
    if args.infeasible_config:
        limit, p90 = infeasible_limit(args.baseline, args.infeasible_config, limits)
        feasibility = {'infeasibleConfiguration': args.infeasible_config, 'infeasibleP90Ms': p90}
        if args.feasible_config:
            incumbent = calibration_p90(args.baseline, args.feasible_config)
            if max(incumbent.values()) > limit:
                raise SystemExit(f'{args.feasible_config} is not feasible at {limit} ms; the rule fails closed')
            feasibility.update(configuration=args.feasible_config, calibrationP90Ms=incumbent)
    elif args.feasible_config:
        limit, p90 = feasible_limit(args.baseline, args.feasible_config, limits)
        feasibility = {'configuration': args.feasible_config, 'calibrationP90Ms': p90}
    if feasibility is not None:
        feasibility.update(baseline=args.baseline, latencyLimitMs=limit,
                           baselineSha256=hashlib.sha256(Path(args.baseline).read_bytes()).hexdigest())
        limits = (limit,)
    raw = Path(args.report).read_bytes()
    decision = select(json.loads(raw), limits, delays)
    record = {'rule': args.rule, 'limits': limits, 'delays': delays, 'feasibility': feasibility,
              'report': args.report, 'reportSha256': hashlib.sha256(raw).hexdigest(), 'decision': decision}
    Path(args.output).write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(decision, indent=2))


if __name__ == '__main__':
    main()
