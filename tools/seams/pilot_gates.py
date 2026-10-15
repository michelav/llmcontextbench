"""Check the pre-registered pilot go/no-go criteria (docs/development/seams2027-preregistration.md).

Reads `analysis.json` of each pilot study (run `llmctxbench eval` and `study analyze`
first) and prints each criterion with its observed value and verdict. Criteria that need
inspection beyond analysis.json (fallback trigger classes, attempt provenance) read the
episode decision logs.
"""
import argparse
import json
from pathlib import Path


def summaries(study):
    report = json.loads((Path(study)/'analysis.json').read_text())
    return {s['policyName']: s for s in report['summaries']}, report


def phase(summary, first, last):
    return next(p for p in summary['phaseSummaries'] if p['firstRequest'] == first and p['lastRequest'] == last)


def lag(summary):
    lags = summary['lags'] or [{}]
    return lags[0].get('reactionLag'), lags[0].get('recoveryLag')


def check(name, value, ok):
    print(f"  {'GO  ' if ok else 'NOGO'} {name}: {value}")
    return ok


def cascade(study):
    s, _ = summaries(study)
    cas, default = s['cascade-mcp'], s['mcp-default']
    ok = check('cascade-mcp final failures == 0', cas['failure'], cas['failure'] == 0)
    ratio = cas['tokensLowerBound']/default['tokensLowerBound']
    ok &= check('cascade-mcp tokens <= 0.8 x mcp-default', f"{cas['tokensLowerBound']} / {default['tokensLowerBound']} = {ratio:.2f}", ratio <= 0.8)
    # The runner falls back when an attempt's failure classes include a trigger class;
    # a step-limit error may also carry the generic 'operation' class.
    triggers, untriggered, logged = set(), 0, True
    for path in Path(study, 'episodes').glob('*/decisions.jsonl'):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            for attempt in row.get('attempts') or []:
                logged &= 'configuration' in attempt and 'tokens' in attempt
            if row.get('fallbackReason'):
                reason = set(row['fallbackReason'] if isinstance(row['fallbackReason'], list) else [row['fallbackReason']])
                triggers |= reason
                untriggered += not reason & {'step-limit', 'tool-use'}
    ok &= check('every fallback carries a trigger class (step-limit, tool-use)',
                f"{untriggered} without; classes seen {sorted(triggers) or 'none'}", untriggered == 0)
    ok &= check('attempts logged with configuration and tokens', logged, logged)
    print(f"  info: fallbacks {cas['fallbacks']}, wasted tokens >= {cas['wastedTokensLowerBound']}, "
          f"mcp-lean failures {s['mcp-lean']['failure']}, function-lean failures {s['function-lean']['failure']}")
    return ok


def degradation(study, delay_ratio):
    s, _ = summaries(study)
    v2, frozen = s['v2'], s['frozen']
    reaction, recovery = lag(v2)
    ok = check('v2 reaction lag <= 5', reaction, reaction is not None and reaction <= 5)
    ok &= check('v2 recovery lag <= 8', recovery, recovery is not None and recovery <= 8)
    a, b = phase(v2, 17, 32)['deadlineMisses'], phase(frozen, 17, 32)['deadlineMisses']
    ok &= check(f'v2 delay-phase misses <= {delay_ratio:.0%} of frozen', f'{a} vs {b}', b > 0 and a <= delay_ratio*b)
    return ok, s


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--cascade', default='studies/pilot-cascade')
    parser.add_argument('--degradation', default='studies/pilot-degradation')
    parser.add_argument('--inline-degradation', default='studies/pilot-inline-degradation')
    args = parser.parse_args()
    print('P1 cascade'); p1 = cascade(args.cascade)
    print('P2 MCP-lean degradation'); p2, _ = degradation(args.degradation, 0.5)
    print('P3 inline degradation'); p3, s = degradation(args.inline_degradation, 0.75)
    p3 &= check('v2 episode tokens <= frozen', f"{s['v2']['tokensLowerBound']} vs {s['frozen']['tokensLowerBound']}",
                s['v2']['tokensLowerBound'] <= s['frozen']['tokensLowerBound'])
    for label, ok in (('P1', p1), ('P2', p2), ('P3', p3)):
        print(f"{label}: {'GO' if ok else 'NO-GO'}")


if __name__ == '__main__':
    main()
