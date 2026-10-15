"""Compare calibration estimates of two frozen baselines (provider drift).

Prints, per configuration and size bin, latency, tokens per request, pass rate and
failures for both baselines and the latency/token ratio (second / first). The values are
the frozen `estimates` (provenance `estimated` from calibration observations).
"""
import argparse
import json
from pathlib import Path


def rows(first, second):
    a, b = (json.loads(Path(p).read_text())['payload']['estimates'] for p in (first, second))
    for cid in sorted(set(a) | set(b)):
        for size in ('small', 'medium', 'large'):
            x, y = a.get(cid, {}).get(size), b.get(cid, {}).get(size)
            if not (x and y):
                continue
            yield {'configuration': cid, 'sizeBin': size,
                   'latencyMs': [round(x['latencyMs']), round(y['latencyMs'])],
                   'latencyRatio': round(y['latencyMs']/x['latencyMs'], 2),
                   'tokens': [round(x['tokens']), round(y['tokens'])],
                   'tokenRatio': round(y['tokens']/x['tokens'], 2),
                   'passRate': [round(x['passRate'], 3), round(y['passRate'], 3)],
                   'failures': [x['failures'], y['failures']]}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('first')
    parser.add_argument('second')
    parser.add_argument('--output')
    args = parser.parse_args()
    result = list(rows(args.first, args.second))
    print(f"{'configuration':24} {'bin':6} {'latency ms':>15} {'ratio':>5} {'tokens':>15} {'ratio':>5} {'pass':>13} fail")
    for r in result:
        print(f"{r['configuration']:24} {r['sizeBin']:6} {r['latencyMs'][0]:>7}→{r['latencyMs'][1]:<7} {r['latencyRatio']:>5} "
              f"{r['tokens'][0]:>7}→{r['tokens'][1]:<7} {r['tokenRatio']:>5} {r['passRate'][0]:>6}→{r['passRate'][1]:<6} "
              f"{r['failures'][0]}→{r['failures'][1]}")
    if args.output:
        Path(args.output).write_text(json.dumps({'first': args.first, 'second': args.second, 'rows': result}, indent=2)+'\n')


if __name__ == '__main__':
    main()
