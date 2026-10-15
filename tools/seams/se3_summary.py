"""S-E' summary: per-arm phase misses and delay-phase paired target-cluster bootstrap.

Usage: python tools/seams/se3_summary.py studies/seams3-inline-degradation
Also imported by make_figures.py and make_tables.py.
"""
import json, sys
from collections import defaultdict
from statistics import mean
from ctxbench.studies.study import _cluster_bootstrap

LIMIT = 7000
PHASES = [(1, 30), (31, 60), (61, 96)]
ARMS = ['inline', 'direct', 'frozen', 'v1', 'v2', 'oracle']
SCENARIOS = ['stationary', 'inline-degraded']
CONTRASTS = [('v2', 'frozen'), ('v2', 'v1'), ('v2', 'direct'), ('v2', 'oracle'), ('v1', 'frozen')]


def load(d):
    """Return (prepared payload, decision rows keyed by (policy, scenario, seed), analysis summaries by the same key)."""
    prep = json.load(open(f'{d}/prepared.json'))['payload']
    an = json.load(open(f'{d}/analysis.json'))
    rows = {}
    for e in prep['episodes']:
        recs = [json.loads(l) for l in open(f"{d}/episodes/{e['id']}/decisions.jsonl")]
        rows[(e['policyName'], e['scenarioName'], e['seed'])] = {r['sequenceIndex']: r for r in recs}
    summ = {(s['policyName'], s['scenarioName'], s['seed']): s for s in an['summaries']}
    return prep, rows, summ


def arm_table(rows, summ):
    """Means per episode over seeds, per (arm, scenario)."""
    out = {}
    for sc in SCENARIOS:
        for a in ARMS:
            ks = [k for k in rows if k[0] == a and k[1] == sc]
            lags = [l for k in ks for l in summ[k]['lags'] if l['configuration'] == 'inline-code-full']
            out[(a, sc)] = {
                'seeds': len(ks),
                'phaseMisses': [mean(sum(r['durationMs'] > LIMIT for i, r in rows[k].items() if lo <= i <= hi) for k in ks)
                                for lo, hi in PHASES],
                'misses': mean(summ[k]['deadlineMisses'] for k in ks),
                'missesBySeed': [summ[k]['deadlineMisses'] for k in sorted(ks)],
                'tokens': mean(summ[k]['tokensLowerBound'] for k in ks),
                'tokensBySeed': [summ[k]['tokensLowerBound'] for k in sorted(ks)],
                'passRate': mean(summ[k]['passRateAllRequests'] for k in ks),
                'directShare': mean(sum(r['configuration'] == 'local-mcp-direct' for r in rows[k].values()) / 96 for k in ks),
                'probes': mean(summ[k]['probes'] for k in ks),
                'switches': mean(summ[k]['switches'] for k in ks),
                'reactionLags': [l['reactionLag'] for l in lags],
                'recoveryLags': [l['recoveryLag'] for l in lags],
            }
    return out


def miss(r):
    return float(r['durationMs'] > LIMIT)


def tokens(r):
    return float(r['tokens']['value'] or r['tokens']['knownPartial'] or 0)


def contrast(prep, rows, left, right, metric, scenario='inline-degraded', lo=31, hi=60):
    """Per-request paired difference (left - right) inside [lo, hi], target-cluster bootstrap within language."""
    units = defaultdict(list)
    for s in prep['definition']['seeds']:
        A, B = rows[(left, scenario, s)], rows[(right, scenario, s)]
        byb = {r['requestId']: r for r in B.values()}
        for i, x in A.items():
            if lo <= i <= hi:
                target = x['requestId'].rsplit('_ctx', 1)[0]
                units[(target.split('_')[0], target)].append(metric(x) - metric(byb[x['requestId']]))
    return _cluster_bootstrap(units, 42, 1000)


def main(d):
    prep, rows, summ = load(d)
    bad = sum(sum(r['durationMs'] > LIMIT for r in rs.values()) != summ[k]['deadlineMisses'] for k, rs in rows.items())
    print('miss recount mismatches:', bad)
    table = arm_table(rows, summ)
    for sc in SCENARIOS:
        print(f'\n== {sc} (means per episode over seeds; misses per phase 1-30/31-60/61-96)')
        print('arm     misses_total  phases              tokens(k)  pass   direct%  probes switches  reactLag recovLag')
        for a in ARMS:
            t = table[(a, sc)]
            ph = t['phaseMisses']
            print(f"{a:7} {t['misses']:6.1f}       {ph[0]:4.1f}/{ph[1]:4.1f}/{ph[2]:4.1f}   {t['tokens']/1000:8.0f}  "
                  f"{t['passRate']:.3f}  {t['directShare']*100:5.1f}   {t['probes']:5.1f} {t['switches']:5.1f}    "
                  f"{t['reactionLags'] if sc != 'stationary' else []} {t['recoveryLags'] if sc != 'stationary' else []}")
    print('\n== delay phase (31-60), paired by request, target-cluster bootstrap, per-request difference')
    for l, r in CONTRASTS:
        m = contrast(prep, rows, l, r, miss); t = contrast(prep, rows, l, r, tokens)
        print(f"{l} - {r}: miss {m['meanDifference']:+.3f} {[round(x,3) for x in m['bootstrap95']]}  "
              f"tokens {t['meanDifference']:+.0f} {[round(x) for x in t['bootstrap95']]}  clusters {m['targetClusters']}")


if __name__ == '__main__':
    main(sys.argv[1])
