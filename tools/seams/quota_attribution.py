"""Diagnose S-B' low capture: where quota waits land and what the routers choose (replay, no provider calls)."""
import json, random, statistics as st, collections
import ctxbench.studies.replay as rp
POLICIES, EFFECTS = rp.POLICIES, rp.EFFECTS
from ctxbench.adapters.repoqa.study import ordered_workload

grid = json.load(open('examples/studies/replay/v3-quota.grid.json'))
point = next(p for p in grid['points'] if p['name'] == 'L7000-q60k-n30')
plan = rp.plan_from_baseline('baselines/repoqa-long64-v3/frozen.json', grid['configurations'], grid['base'])
plan = {**plan, 'definition': {**plan['definition'], 'latencyLimitMs': 7000}}
pool = rp.load_pool(plan)
policies = {n: p.model_dump() for n, p in POLICIES.validate_python({**grid['policies'], **point['policies']}).items()}
effects = [e.model_dump() for e in EFFECTS.validate_python(point['effects'])]
waits = []
original = rp.quota_wait_seconds
rp.quota_wait_seconds = lambda *a: waits.append(original(*a)) or waits[-1]
LIMIT, FIRST, LAST = 7000, 31, 60
out, summary = {}, {}
for name in ('frozen', 'v2-rr10-ttl8', 'v2-t10-ttl10', 'oracle-split', 'direct', 'inline'):
    stats = collections.defaultdict(list)
    for seed in grid['seeds']:
        workload = [r['instanceId'] for r in ordered_workload(plan['index'], plan['split']['heldOut'], seed)]
        for rep in range(10):
            episode = {'policyName': name, 'scenarioName': point['name'], 'seed': seed, 'repeat': rep+1,
                       'workload': workload, 'policy': policies[name], 'scenario': effects, 'id': f'{name}{seed}{rep}'}
            rng = random.Random(f"0:{point['name']}:{seed}:{rep}")
            waits.clear()
            rows = rp.simulate(plan, episode, effects, pool, rng)
            active = [w for w in waits]  # one call per request (no fallbacks), only inside the quota phase
            phase = [r for r in rows if FIRST <= r['sequenceIndex'] <= LAST]
            for r in rows:
                i = r['sequenceIndex']
                w = waits[i-FIRST] if FIRST <= i <= LAST and len(waits) == LAST-FIRST+1 else 0.0
                key = ('in' if FIRST <= i <= LAST else 'after' if i > LAST else 'before')
                stats[(key, r['configuration'], r['sizeBin'])].append((r['durationMs'], w or 0.0, r['probe']))
    out[name] = stats
    print(f'== {name}')
    for key in sorted(stats, key=lambda k: (['before','in','after'].index(k[0]), k[1] or '', k[2])):
        if key[0] == 'before': continue
        rows = stats[key]
        print(f"  {key[0]:5} {str(key[1]).replace('local-mcp-',''):16} {key[2]:6} n/ep={len(rows)/30:5.1f} "
              f"wait={st.mean(w for _,w,_ in rows):5.1f}s miss={sum(d>LIMIT for d,_,_ in rows)/30:4.1f}/ep "
              f"miss-with-wait={sum(d>LIMIT and w>0 for d,w,_ in rows)/30:4.1f}/ep probes={sum(p for *_,p in rows)/30:.1f}")
        summary.setdefault(name, []).append({'phase': key[0], 'configuration': key[1], 'sizeBin': key[2],
            'requestsPerEpisode': len(rows)/30, 'meanWaitS': st.mean(w for _,w,_ in rows),
            'missesPerEpisode': sum(d>LIMIT for d,_,_ in rows)/30,
            'missesWithWaitPerEpisode': sum(d>LIMIT and w>0 for d,w,_ in rows)/30})
json.dump({'point': point['name'], 'provenance': 'estimated', 'episodesPerPolicy': 30, 'policies': summary},
          open('studies/replay-v3calib/quota-attribution.json', 'w'), indent=1)
