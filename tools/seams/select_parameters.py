"""Apply the pre-registered S-A selection rule to a degradation replay report.

Rule (docs/development/seams2027-preregistration.md):
1. Among `n30` points with limit 10000 or 12000 ms and delay 2000 or 3000 ms, choose
   the largest frozen − oracle miss gap; ties go to the smaller delay.
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


def select(report):
    points = {p['name']: p for p in report['points']}
    eligible_points = [points[f'L{limit}-d{delay}-n{DURATION}'] for limit in LIMITS for delay in DELAYS]
    chosen = max(eligible_points, key=lambda p: (p['opportunity'], -p['effects'][0]['delayMs']))
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
    args = parser.parse_args()
    raw = Path(args.report).read_bytes()
    decision = select(json.loads(raw))
    record = {'rule': 'seams2027-preregistration S-A v1', 'report': str(Path(args.report).resolve()),
              'reportSha256': hashlib.sha256(raw).hexdigest(), 'decision': decision}
    Path(args.output).write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(decision, indent=2))


if __name__ == '__main__':
    main()
