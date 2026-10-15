"""S-E' summary: per-arm phase misses and delay-phase paired target-cluster bootstrap.

Usage: python tools/seams/se3_summary.py studies/seams3-inline-degradation
"""
import json, sys
from collections import defaultdict
from statistics import mean
from ctxbench.studies.study import _cluster_bootstrap
d = sys.argv[1]
prep = json.load(open(f'{d}/prepared.json'))['payload']
an = json.load(open(f'{d}/analysis.json'))
LIMIT = 7000
PH = [(1,30),(31,60),(61,96)]
rows = {}
for e in prep['episodes']:
    recs = [json.loads(l) for l in open(f"{d}/episodes/{e['id']}/decisions.jsonl")]
    rows[(e['policyName'], e['scenarioName'], e['seed'])] = {r['sequenceIndex']: r for r in recs}
summ = {(s['policyName'], s['scenarioName'], s['seed']): s for s in an['summaries']}
# consistency: phase misses from decisions vs analysis
bad = 0
for k, rs in rows.items():
    m = sum(r['durationMs'] > LIMIT for r in rs.values())
    bad += m != summ[k]['deadlineMisses']
print('miss recount mismatches:', bad)
arms = ['inline','direct','frozen','v1','v2','oracle']
for sc in ['stationary','inline-degraded']:
    print(f'\n== {sc} (means per episode over 5 seeds; misses per phase 1-30/31-60/61-96)')
    print('arm     misses_total  phases              tokens(k)  pass   direct%  probes switches  reactLag recovLag')
    for a in arms:
        ks = [k for k in rows if k[0]==a and k[1]==sc]
        ph = [mean(sum(r['durationMs']>LIMIT for i,r in rows[k].items() if lo<=i<=hi) for k in ks) for lo,hi in PH]
        tot = mean(summ[k]['deadlineMisses'] for k in ks)
        tok = mean(summ[k]['tokensLowerBound'] for k in ks)/1000
        pr = mean(summ[k]['passRateAllRequests'] for k in ks)
        dp = mean(sum(r['configuration']=='local-mcp-direct' for r in rows[k].values())/96 for k in ks)*100
        probes = mean(summ[k]['probes'] for k in ks); sw = mean(summ[k]['switches'] for k in ks)
        lags = [l for k in ks for l in summ[k]['lags'] if l['configuration']=='inline-code-full']
        rl = [l['reactionLag'] for l in lags]; rc = [l['recoveryLag'] for l in lags]
        print(f"{a:7} {tot:6.1f}       {ph[0]:4.1f}/{ph[1]:4.1f}/{ph[2]:4.1f}   {tok:8.0f}  {pr:.3f}  {dp:5.1f}   {probes:5.1f} {sw:5.1f}    {rl} {rc}")
# delay-phase paired cluster bootstrap
def boot(left, right, sc, metric, lo, hi):
    units = defaultdict(list)
    for s in prep['definition']['seeds']:
        A, B = rows[(left,sc,s)], rows[(right,sc,s)]
        bya = {r['requestId']: r for i,r in A.items() if lo<=i<=hi}
        byb = {r['requestId']: r for r in B.values()}
        for rid, x in bya.items():
            y = byb[rid]
            tgt = rid.rsplit('_ctx',1)[0]
            units[(tgt.split('_')[0], tgt)].append(metric(x)-metric(y))
    return _cluster_bootstrap(units, 42, 1000)
miss = lambda r: float(r['durationMs'] > LIMIT)
tok = lambda r: float(r['tokens']['value'] or r['tokens']['knownPartial'] or 0)
print('\n== delay phase (31-60), paired by request, target-cluster bootstrap, per-request difference')
for l, r in [('v2','frozen'),('v2','v1'),('v2','direct'),('v2','oracle'),('v1','frozen')]:
    m = boot(l, r, 'inline-degraded', miss, 31, 60); t = boot(l, r, 'inline-degraded', tok, 31, 60)
    print(f"{l} - {r}: miss {m['meanDifference']:+.3f} {[round(x,3) for x in m['bootstrap95']]}  tokens {t['meanDifference']:+.0f} {[round(x) for x in t['bootstrap95']]}  clusters {m['targetClusters']}")
