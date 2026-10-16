"""SEAMS 2027 figures from the replay reports, the pilots and the S-E' live study (no provider calls).

Usage: python tools/seams/make_figures.py [--out docs/seams2027/figures] [--format pdf]

Replay results are labelled `estimated`; live results come from `analysis.json` and decision logs.
"""
import argparse, json, os
os.environ.setdefault("SOURCE_DATE_EPOCH", "0")  # reproducible PDF metadata
from pathlib import Path
from itertools import accumulate
from statistics import mean
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import se3_summary as se3

REPLAY = Path('studies/replay-v3calib')
LIVE = 'studies/seams3-inline-degradation'
POLICY = 'v2-t10-ttl10'
WIDE, NARROW = (7.0, 2.6), (3.4, 2.4)
COLORS = {'inline': '#7f7f7f', 'direct': '#2ca02c', 'frozen': '#1f77b4', 'v1': '#ff7f0e', 'v2': '#d62728',
          'oracle': '#9467bd', 'lean': '#8c564b'}
plt.rcParams.update({'font.size': 8, 'axes.titlesize': 8, 'axes.labelsize': 8, 'legend.fontsize': 7,
                     'xtick.labelsize': 7, 'ytick.labelsize': 7, 'pdf.fonttype': 42, 'axes.spines.top': False,
                     'axes.spines.right': False})


def points(name):
    return json.load(open(REPLAY / f'{name}.json'))['points']


def misses(point, policy):
    return point['policies'][policy]['deadlineMisses']


def opportunity_map(ax_row):
    """Replay: room for adaptation (frozen - oracle) against what v2 recovers (frozen - v2), per grid point."""
    families = [('inline-degradation', 'S-E′: inline delayed', 'oracle', 'L7000-d9000-n30'),
                ('quota', 'S-B′: token quota', 'oracle-split', 'L7000-q60k-n30'),
                ('direct-degradation', 'S-F: direct delayed', 'oracle', None),
                ('round-trip', 'Round-trip delay', 'oracle', None)]
    limits = {6000: 'o', 7000: 's', 8000: '^', 10000: 'D', 12000: 'v'}
    for ax, (name, title, oracle, selected) in zip(ax_row, families):
        for p in points(name):
            if p['name'].startswith('stationary') or oracle not in p['policies']:
                continue
            x = misses(p, 'frozen') - misses(p, oracle)
            y = misses(p, 'frozen') - misses(p, POLICY)
            ax.scatter(x, y, marker=limits[p['latencyLimitMs']], s=14, color=COLORS['v2'], alpha=.65, linewidths=0)
            if p['name'] == selected:
                ax.scatter(x, y, marker=limits[p['latencyLimitMs']], s=60, facecolors='none', edgecolors='k', linewidths=.8)
        lo, hi = ax.get_xlim()[0], max(ax.get_xlim()[1], ax.get_ylim()[1])
        ax.plot([min(lo, 0), hi], [min(lo, 0), hi], color='k', lw=.6, ls='--')
        ax.axhline(0, color='k', lw=.5)
        ax.set_title(title)
        ax.set_xlabel('frozen − oracle misses')
    ax_row[0].set_ylabel('frozen − v2 misses')
    for limit, marker in limits.items():
        ax_row[-1].scatter([], [], marker=marker, color=COLORS['v2'], s=14, label=f'{limit/1000:g} s')
    ax_row[-1].legend(title='limit', frameon=False, loc='upper left')


def fig_opportunity(out, fmt):
    fig, axes = plt.subplots(1, 4, figsize=WIDE)
    opportunity_map(axes)
    fig.text(.5, -.04, 'Replay (estimated), misses per 96-request episode; dashed: v2 captures all the opportunity; '
             'circled: selected point', ha='center', fontsize=7)
    fig.tight_layout()
    fig.savefig(out / f'replay-opportunity.{fmt}', bbox_inches='tight')


def fig_timeline(out, fmt):
    """Live S-E′, inline degraded: share of seeds missing the deadline and share routed to direct, per request."""
    prep, rows, _ = se3.load(LIVE)
    seeds = prep['definition']['seeds']
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(7.0, 3.4), sharex=True, gridspec_kw={'height_ratios': [3, 2]})
    xs = list(range(1, 97))
    def smooth(values, k=5):
        return [mean(values[max(0, i-k//2):i+k//2+1]) for i in range(len(values))]
    for arm in ('frozen', 'v1', 'v2', 'direct'):
        rate = [mean(se3.miss(rows[(arm, 'inline-degraded', s)][i]) for s in seeds) for i in xs]
        top.plot(xs, smooth(rate), color=COLORS[arm], lw=1.2, label=arm)
    for arm in ('v1', 'v2'):
        share = [mean(rows[(arm, 'inline-degraded', s)][i]['configuration'] == 'local-mcp-direct' for s in seeds) for i in xs]
        bottom.plot(xs, smooth(share), color=COLORS[arm], lw=1.2, label=arm)
    for ax in (top, bottom):
        ax.axvspan(31, 60, color='0.9', zorder=0)
        ax.set_ylim(-.02, 1.02)
    top.set_ylabel('deadline-miss rate')
    top.legend(frameon=False, ncol=4, loc='upper right')
    top.text(45.5, .7, 'inline +9 s', ha='center', va='top', fontsize=7)
    bottom.set_ylabel('share to direct')
    bottom.set_xlabel(f'request position (5 seeds, moving average over 5 requests; limit {se3.LIMIT/1000:g} s)')
    bottom.legend(frameon=False, ncol=2, loc='upper right')
    fig.tight_layout()
    fig.savefig(out / f'se-timeline.{fmt}', bbox_inches='tight')


LABEL_OFFSETS = {'inline': (-30, 1.2, 'right'), 'frozen': (-30, -2.5, 'right'), 'oracle': (-30, 1.5, 'right')}


def fig_tradeoff(out, fmt):
    """Live S-E′: tokens against misses per episode, per arm, seed range as bars."""
    _, rows, summ = se3.load(LIVE)
    table = se3.arm_table(rows, summ)
    fig, ax = plt.subplots(figsize=NARROW)
    for arm in se3.ARMS:
        for scenario, fill in (('stationary', 'none'), ('inline-degraded', COLORS[arm])):
            t = table[(arm, scenario)]
            x, y = t['tokens']/1e3, t['misses']
            ax.errorbar(x, y, yerr=[[y - min(t['missesBySeed'])], [max(t['missesBySeed']) - y]],
                        xerr=[[x - min(t['tokensBySeed'])/1e3], [max(t['tokensBySeed'])/1e3 - x]],
                        fmt='o', ms=5, color=COLORS[arm], mfc=fill, lw=.7, capsize=1.5)
        a, b = table[(arm, 'stationary')], table[(arm, 'inline-degraded')]
        ax.annotate('', xy=(b['tokens']/1e3, b['misses']), xytext=(a['tokens']/1e3, a['misses']),
                    arrowprops={'arrowstyle': '->', 'color': COLORS[arm], 'lw': .6, 'alpha': .6})
        dx, dy, ha = LABEL_OFFSETS.get(arm, (25, .6, 'left'))
        ax.text(b['tokens']/1e3 + dx, b['misses'] + dy, arm, color=COLORS[arm], fontsize=7, ha=ha)
    ax.set_xlabel('answer tokens per episode (thousands, lower bound)')
    ax.set_ylabel('deadline misses per episode')
    ax.scatter([], [], marker='o', facecolors='none', edgecolors='k', s=20, label='stationary')
    ax.scatter([], [], marker='o', color='k', s=20, label='inline delayed')
    ax.legend(frameon=False, loc='upper left')
    fig.tight_layout()
    fig.savefig(out / f'se-tradeoff.{fmt}', bbox_inches='tight')


def fig_pilots(out, fmt):
    """Live pilots P3 (lean fallback, 10 s) and P3′ (direct fallback, 7 s): misses per phase."""
    pilots = [('studies/pilot-inline-degradation', 'P3: fallback MCP lean, limit 10 s'),
              ('studies/pilot-v3-inline-degradation', 'P3′: fallback MCP direct, limit 7 s')]
    arms = ['inline', 'frozen', 'v1', 'v2']
    fig, axes = plt.subplots(1, 2, figsize=WIDE, sharey=True)
    for ax, (path, title) in zip(axes, pilots):
        summaries = {s['policyName']: s for s in json.load(open(f'{path}/analysis.json'))['summaries']}
        for j, phase in enumerate(('before', 'delay', 'after')):
            for k, arm in enumerate(arms):
                value = summaries[arm]['phaseSummaries'][j]['deadlineMisses']
                ax.bar(j + (k - 1.5) * .2, value, .2, color=COLORS[arm], label=arm if j == 0 else None)
        ax.set_xticks(range(3), ['requests 1–16', '17–32 (inline +9 s)', '33–48'])
        ax.set_title(title)
    axes[0].set_ylabel('deadline misses (1 episode, 48 requests)')
    axes[1].legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out / f'pilots-p3.{fmt}', bbox_inches='tight')


def fig_round_trip(out, fmt):
    """Replay: exposure of each surface to a per-call delay (30-request phase)."""
    pts = {p['name']: p for p in points('round-trip')}
    fig, axes = plt.subplots(1, 2, figsize=WIDE, sharey=True)
    for ax, limit in zip(axes, (8000, 10000)):
        delays = [0, 1000, 2000, 3000]
        for arm in ('inline', 'direct', 'lean', 'frozen', POLICY):
            ys = [misses(pts[f'stationary-L{limit}'] if d == 0 else pts[f'L{limit}-d{d}-n30'], arm) for d in delays]
            key = 'v2' if arm == POLICY else arm
            ax.plot([d/1000 for d in delays], ys, marker='o', ms=3, color=COLORS[key], label=key)
        ax.set_title(f'limit {limit/1000:g} s')
        ax.set_xlabel('added delay per tool call (s), requests 31–60')
        ax.set_xticks([0, 1, 2, 3])
    axes[0].set_ylabel('misses per episode (replay, estimated)')
    axes[1].legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out / f'replay-round-trip.{fmt}', bbox_inches='tight')


def fig_quota(out, fmt):
    """Replay S-B′: misses in the quota phase by configuration, split by whether the request waited for the quota."""
    data = json.load(open(REPLAY / 'quota-attribution.json'))
    policies = [('direct', 'fixed direct'), ('inline', 'fixed inline'), ('frozen', 'frozen'), (POLICY, 'v2')]
    fig, ax = plt.subplots(figsize=NARROW)
    for i, (name, label) in enumerate(policies):
        bottom = 0
        for config, color in (('inline-code-full', COLORS['inline']), ('local-mcp-direct', COLORS['direct'])):
            cells = [c for c in data['policies'][name] if c['phase'] == 'in' and c['configuration'] == config]
            waited = sum(c['missesWithWaitPerEpisode'] for c in cells)
            other = sum(c['missesPerEpisode'] for c in cells) - waited
            ax.bar(i, waited, .6, bottom=bottom, color=color, hatch='////', edgecolor='white', lw=0)
            ax.bar(i, other, .6, bottom=bottom + waited, color=color)
            bottom += waited + other
    ax.set_xticks(range(len(policies)), [label for _, label in policies])
    ax.set_ylabel('misses in quota phase per episode')
    ax.bar(0, 0, color=COLORS['inline'], label='on inline')
    ax.bar(0, 0, color=COLORS['direct'], label='on direct')
    ax.bar(0, 0, color='0.6', hatch='////', edgecolor='white', label='request waited for quota')
    ax.set_ylim(0, 13)
    ax.legend(frameon=False, loc='upper left', ncol=2)
    ax.set_title(f"Replay (estimated), {data['point']}")
    fig.tight_layout()
    fig.savefig(out / f'replay-quota-attribution.{fmt}', bbox_inches='tight')


def fig_limit_sweep(out, fmt):
    """Replay: misses against the latency limit, without and with the S-E′ delay, and summed over both."""
    pts = {p['name']: p['policies'] for p in points('limit-sweep')}
    limits = sorted({int(n.split('L')[1].split('-')[0]) for n in pts})
    _, rows, summ = se3.load(LIVE)
    live = se3.arm_table(rows, summ)
    arms = ['inline', 'direct', 'frozen', 'v1', 'v2', 'oracle']
    fig, axes = plt.subplots(1, 3, figsize=WIDE, sharey=False)
    for ax, title, scenarios in ((axes[0], 'no delay', ['stationary']),
                                 (axes[1], 'inline +9 s on requests 31–60', ['inline-degraded']),
                                 (axes[2], 'sum of both', ['stationary', 'inline-degraded'])):
        for arm in arms:
            if arm == 'oracle' and len(scenarios) > 1:
                continue
            ys = [sum(pts[f'stationary-L{l}' if s == 'stationary' else f'L{l}-d9000-n30'][arm]['deadlineMisses']
                      for s in scenarios) for l in limits]
            ax.plot([l/1000 for l in limits], ys, marker='o', ms=2.5, lw=1.1, color=COLORS[arm], label=arm,
                    ls=':' if arm == 'oracle' else '-')
            if arm != 'oracle':
                ax.scatter(se3.LIMIT/1000, sum(live[(arm, s)]['misses'] for s in scenarios), marker='*', s=40,
                           color=COLORS[arm], edgecolors='k', linewidths=.4, zorder=5)
        ax.axvspan(4.7, 5.5, color='0.92', zorder=0)
        ax.axvspan(7.0, 7.4, color='#d9f0d3', zorder=0)
        ax.set_title(title)
        ax.set_xlabel('latency limit (s)')
        ax.set_ylim(bottom=0)
    axes[0].set_ylabel('misses per episode')
    axes[0].text(5.1, axes[0].get_ylim()[1]*.97, 'inline\np90', ha='center', va='top', fontsize=6)
    axes[0].text(7.2, axes[0].get_ylim()[1]*.97, 'direct\np90', ha='center', va='top', fontsize=6)
    axes[2].legend(frameon=False, fontsize=6)
    fig.text(.5, -.05, 'Lines: replay (estimated), 30 episodes per point; stars: S-E′ live means at 7 s (5 seeds); '
             'bands: calibration p90 range across size bins', ha='center', fontsize=7)
    fig.tight_layout()
    fig.savefig(out / f'replay-limit-sweep.{fmt}', bbox_inches='tight')


BIN_COLORS = {'small': '#0072B2', 'medium': '#E69F00', 'large': '#CC79A7'}  # Okabe-Ito, colour-blind safe
CONFIG_LABELS = {'inline-code-full': 'inline', 'local-mcp-direct': 'MCP direct'}


def nearest_rank(ys, q):
    """Nearest-rank quantile of sorted values, as in the deadline rule."""
    return ys[max(0, -(-int(q*100)*len(ys)//100)-1)]


def fig_deadline_origin(out, fmt):
    """Calibration latency per configuration and size bin as box plots (whiskers p10-p90), with the candidate limits."""
    import random
    observations = json.load(open('baselines/repoqa-long64-v3/frozen.json'))['payload']['observations']
    rng = random.Random(0)
    fig, ax = plt.subplots(figsize=NARROW)
    groups = [(c, b) for c in CONFIG_LABELS for b in BIN_COLORS]
    stats = []
    for x, (config, size) in enumerate(groups):
        ys = sorted(o['durationMs']/1000 for o in observations if o['configuration'] == config and o['sizeBin'] == size)
        p10, q1, med, q3, p90 = (nearest_rank(ys, q) for q in (.1, .25, .5, .75, .9))
        stats.append({'med': med, 'q1': q1, 'q3': q3, 'whislo': p10, 'whishi': p90, 'fliers': []})
        ax.scatter([x + rng.uniform(-.18, .18) for _ in ys], ys, s=4, color=BIN_COLORS[size], alpha=.45, linewidths=0, zorder=2)
        ax.text(x + .27, p90 + .15, f'{p90:.1f}', va='bottom', ha='left', fontsize=6)
    ax.bxp(stats, positions=range(len(groups)), widths=.5, showfliers=False, patch_artist=True, zorder=3,
           boxprops={'facecolor': 'none', 'lw': .8}, medianprops={'color': 'k', 'lw': 1},
           whiskerprops={'lw': .8}, capprops={'lw': 1.2})
    for limit in (6, 8):
        ax.axhline(limit, color='0.6', lw=.6, ls=':')
    ax.axhline(7, color='k', lw=1, ls='--')
    ax.text(-.45, 7.15, 'limit 7 s (candidates 6, 8 s dotted)', ha='left', va='bottom', fontsize=6)
    ax.axvline(2.5, color='0.8', lw=.5)
    ax.set_xticks(range(6), list(BIN_COLORS) * 2)
    for x, config in ((1, 'inline'), (4, 'MCP direct')):
        ax.text(x, -.17, config, transform=ax.get_xaxis_transform(), ha='center', fontsize=8)
    ax.set_ylabel('request latency (s)')
    ax.set_ylim(0, 14)
    ax.set_title('Calibration, 48 requests per box; whiskers p10-p90 (p90 labelled)', fontsize=7)
    fig.tight_layout()
    fig.savefig(out / f'deadline-origin.{fmt}', bbox_inches='tight')


ROUTERS = ('frozen', 'v1', 'v2')
ROUTER_NAMES = {'frozen': 'frozen router', 'v1': 'adaptive v1', 'v2': 'adaptive v2'}
GREY = '0.82'
INLINE = 'inline-code-full'


def degraded_requests():
    """Every live S-E' request with the inline delay, as (arm, seed, position, prepared request, decision)."""
    prep, rows, _ = se3.load(LIVE)
    return [(arm, seed, i, prep['requests'][r['requestId']], r) for (arm, scenario, seed), episode in sorted(rows.items())
            if scenario == 'inline-degraded' for i, r in sorted(episode.items())]


def dots(ax, xs, ys, color, size=9, highlight=False, zorder=3):
    """Borderless circles; a black border marks the requests the caption explains."""
    ax.scatter(xs, ys, s=size, color=color, linewidths=.7 if highlight else 0, edgecolors='k' if highlight else 'none',
               zorder=zorder + highlight)


def callout(ax, text, xy, xytext):
    ax.annotate(text, xy=xy, xytext=xytext, fontsize=6.5, ha='center', va='center', zorder=6,
                bbox={'boxstyle': 'round,pad=.25', 'fc': 'white', 'ec': '0.4', 'lw': .5},
                arrowprops={'arrowstyle': '-', 'color': '0.3', 'lw': .5})


def fig_requests(out, fmt):
    """Live S-E', inline delayed, all seeds: every request in grey, router misses in colour, two v2 groups outlined."""
    import random
    requests = degraded_requests()
    seeds = sorted({seed for _, seed, *_ in requests})
    rng = random.Random(0)
    jitter = lambda i: i + rng.uniform(-.35, .35)
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    ax.axvspan(30.5, 60.5, color='0.95', zorder=0)
    ax.text(45.5, 23.3, 'inline +9 s (requests 31-60)', ha='center', va='top', fontsize=6.5, color='0.35')
    dots(ax, [jitter(i) for _, _, i, _, _ in requests], [r['durationMs']/1000 for *_, r in requests], GREY, 6, zorder=1)
    handles = [plt.Line2D([], [], ls='', marker='o', mew=0, color=GREY, label=f'all requests, 6 arms (n={len(requests)})')]
    probes, late = [], []
    for arm in ROUTERS:
        missed = [(i, r) for a, _, i, _, r in requests if a == arm and r['durationMs'] > se3.LIMIT]
        for i, r in missed:
            if arm == 'v2' and 31 <= i <= 60 and r['probe']:
                probes.append((jitter(i), r['durationMs']/1000))
            elif arm == 'v2' and i > 60 and r['configuration'] != INLINE:
                late.append((jitter(i), r['durationMs']/1000))
            else:
                dots(ax, jitter(i), r['durationMs']/1000, COLORS[arm])
        handles.append(plt.Line2D([], [], ls='', marker='o', mew=0, color=COLORS[arm],
                                  label=f'{ROUTER_NAMES[arm]} misses (n={len(missed)})'))
    for group in (probes, late):
        dots(ax, [x for x, _ in group], [y for _, y in group], COLORS['v2'], highlight=True)
    callout(ax, f'v2 probes inline during the delay:\n{len(probes)} of its {sum(1 for a, _, i, _, r in requests if a == "v2" and 31 <= i <= 60 and r["durationMs"] > se3.LIMIT)} misses there',
            (47, 15.5), (40, 20.5))
    callout(ax, f'v2 stays on direct after the delay\n(back to inline 0-12 requests after it ends): {len(late)} misses',
            (75, 9.5), (80, 13.2))
    ax.axhline(se3.LIMIT/1000, color='k', lw=1, ls='--', zorder=5)
    handles.append(plt.Line2D([], [], color='k', ls='--', label='latency limit 7 s'))
    ax.set_xlim(0, 97)
    ax.set_ylim(0, 24)
    ax.set_xlabel(f'request position in the episode ({len(seeds)} seeds, {min(seeds)}-{max(seeds)})')
    ax.set_ylabel('request latency (s)')
    ax.legend(handles=handles, loc='upper left', fontsize=6.5, framealpha=.95)
    inset = ax.inset_axes([.73, .71, .26, .26])
    inset.axvspan(30.5, 60.5, color='0.95')
    window = 5
    for arm in ROUTERS:
        miss = {i: 0 for i in range(1, 97)}
        for a, _, i, _, r in requests:
            if a == arm:
                miss[i] += r['durationMs'] > se3.LIMIT
        share = [mean(miss[j] for j in range(max(1, i - window//2), min(96, i + window//2) + 1))/len(seeds)
                 for i in range(1, 97)]
        inset.plot(range(1, 97), share, color=COLORS[arm], lw=1)
    inset.set_xlim(1, 96)
    inset.set_ylim(0, 1.05)
    inset.set_title(f'share of seeds missing ({window}-request mean)', fontsize=6)
    inset.tick_params(labelsize=5.5)
    inset.set_xticks([1, 31, 61, 96])
    fig.tight_layout()
    fig.savefig(out / f'se-requests.{fmt}', bbox_inches='tight')


VARIANTS = ('2k', '4k', '8k', '16k', '32k', '64k')


def fig_request_sizes(out, fmt):
    """Live S-E', inline delayed, all seeds: latency per context size; router requests during the delay side by side."""
    import random
    requests = degraded_requests()
    rng = random.Random(0)
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    for k in range(1, len(VARIANTS), 2):
        ax.axvspan(k - .5, k + .5, color='0.97', zorder=0)
    x = lambda request: VARIANTS.index(request['variant'])
    dots(ax, [x(q) + rng.uniform(-.42, .42) for *_, q, _ in requests], [r['durationMs']/1000 for *_, r in requests],
         GREY, 6, zorder=1)
    handles = [plt.Line2D([], [], ls='', marker='o', mew=0, color=GREY, label=f'all requests, 6 arms (n={len(requests)})')]
    reverted = []
    for offset, arm in zip((-.27, 0, .27), ROUTERS):
        delayed = [(q, r) for a, _, i, q, r in requests if a == arm and 31 <= i <= 60]
        for q, r in delayed:
            point = (x(q) + offset + rng.uniform(-.1, .1), r['durationMs']/1000)
            if arm == 'v2' and r['configuration'] == INLINE and not r['probe'] and r['durationMs'] > se3.LIMIT:
                reverted.append(point)
            else:
                dots(ax, *point, COLORS[arm])
        missed = sum(r['durationMs'] > se3.LIMIT for _, r in delayed)
        handles.append(plt.Line2D([], [], ls='', marker='o', mew=0, color=COLORS[arm],
                                  label=f'{ROUTER_NAMES[arm]}, requests 31-60 (n={len(delayed)}, {missed} missed)'))
    dots(ax, [p[0] for p in reverted], [p[1] for p in reverted], COLORS['v2'], highlight=True)
    handles.append(plt.Line2D([], [], ls='', marker='o', color=COLORS['v2'], mec='k', mew=.7,
                              label=f'v2 routed to inline (not a probe) and missed (n={len(reverted)})'))
    ax.axhline(se3.LIMIT/1000, color='k', lw=1, ls='--', zorder=5)
    handles.append(plt.Line2D([], [], color='k', ls='--', label='latency limit 7 s'))
    ax.set_xticks(range(len(VARIANTS)), VARIANTS)
    ax.set_xlim(-.5, len(VARIANTS) - .5)
    for center, name in ((.5, 'small'), (2.5, 'medium'), (4.5, 'large')):
        ax.text(center, -.13, name, transform=ax.get_xaxis_transform(), ha='center', fontsize=7, color='0.35')
    ax.set_xlabel('context size (size bin below); colour columns: frozen, v1, v2', labelpad=12)
    ax.set_ylabel('request latency (s)')
    ax.set_ylim(0, 21.5)
    ax.legend(handles=handles, loc='upper left', bbox_to_anchor=(0, -.2), ncol=2, frameon=False, fontsize=6.5)
    fig.tight_layout()
    fig.savefig(out / f'se-request-sizes.{fmt}', bbox_inches='tight')


ARM_NAMES = {'inline': 'fixed inline', 'direct': 'fixed MCP direct', 'frozen': 'frozen router', 'v1': 'adaptive v1',
             'v2': 'adaptive v2', 'oracle': 'phase oracle'}


def end_labels(ax, ends, fmt, gap):
    """Label line ends at the right edge, pushed apart so they do not overlap."""
    placed = []
    for arm, y in sorted(ends.items(), key=lambda item: item[1]):
        ty = max(y, placed[-1] + gap) if placed else y
        placed.append(ty)
        ax.annotate(fmt(y), (96, y), xytext=(99, ty), textcoords='data', va='center', fontsize=6,
                    color=COLORS[arm], annotation_clip=False)


def fig_economy(out, fmt):
    """Live S-E', inline delayed: cumulative tokens and misses per arm over the episode (mean of seeds; tokens band min-max)."""
    _, rows, _ = se3.load(LIVE)
    xs = range(1, 97)
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(7.0, 4.6), sharex=True, gridspec_kw={'height_ratios': [3, 2]})
    token_ends, miss_ends = {}, {}
    for arm in ('inline', 'frozen', 'v1', 'v2', 'oracle', 'direct'):
        episodes = [e for (a, scenario, _), e in sorted(rows.items()) if a == arm and scenario == 'inline-degraded']
        tokens = [list(accumulate(se3.tokens(e[i])/1e3 for i in xs)) for e in episodes]
        misses = [list(accumulate(se3.miss(e[i]) for i in xs)) for e in episodes]
        style = {'color': COLORS[arm], 'lw': 1.2, 'ls': ':' if arm == 'oracle' else '-', 'label': ARM_NAMES[arm]}
        top.fill_between(xs, [min(c) for c in zip(*tokens)], [max(c) for c in zip(*tokens)], color=COLORS[arm],
                         alpha=.12, lw=0)
        top.plot(xs, [mean(c) for c in zip(*tokens)], **style)
        bottom.plot(xs, [mean(c) for c in zip(*misses)], **style)
        token_ends[arm], miss_ends[arm] = mean(t[-1] for t in tokens), mean(m[-1] for m in misses)
    end_labels(top, token_ends, lambda y: f'{y:.0f}k', 60)
    end_labels(bottom, miss_ends, lambda y: f'{y:.1f}', 2.0)
    for ax in (top, bottom):
        ax.axvspan(30.5, 60.5, color='0.95', zorder=0)
    top.set_ylabel('cumulative answer\ntokens (thousands)')
    bottom.set_ylabel('cumulative\ndeadline misses')
    bottom.set_xlabel('request position in the episode (inline +9 s on requests 31-60 shaded; '
                      'mean of 5 seeds, tokens band: min-max)')
    bottom.set_xlim(1, 96)
    top.legend(loc='upper left', ncol=2, frameon=False)
    fig.tight_layout()
    fig.savefig(out / f'se-economy.{fmt}', bbox_inches='tight')


def fig_savings(out, fmt):
    """Live S-E', inline delayed: tokens saved against fixed inline per arm, stacked by context size, with misses."""
    prep, rows, _ = se3.load(LIVE)
    variant = {rid: r['variant'] for rid, r in prep['requests'].items()}
    arms = ('frozen', 'v1', 'v2', 'oracle', 'direct')
    seeds = sorted({seed for _, scenario, seed in rows if scenario == 'inline-degraded'})
    shades = dict(zip(VARIANTS, plt.cm.viridis_r([.1, .25, .4, .55, .72, .9])))
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.1), sharey=True)
    for ax, (lo, hi, title) in zip(axes, ((31, 60, 'during the delay (requests 31-60)'),
                                         (1, 96, 'whole episode (requests 1-96)'))):
        for x, arm in enumerate(arms):
            saved, misses = {v: 0.0 for v in VARIANTS}, 0
            for seed in seeds:
                base = {r['requestId']: se3.tokens(r) for r in rows[('inline', 'inline-degraded', seed)].values()}
                for i, r in rows[(arm, 'inline-degraded', seed)].items():
                    if lo <= i <= hi:
                        saved[variant[r['requestId']]] += (base[r['requestId']] - se3.tokens(r))/len(seeds)/1e3
                        misses += r['durationMs'] > se3.LIMIT
            up = down = 0.0
            for v in VARIANTS:
                ax.bar(x, saved[v], bottom=up if saved[v] >= 0 else down, color=shades[v], width=.65, lw=0)
                up, down = (up + saved[v], down) if saved[v] >= 0 else (up, down + saved[v])
            ax.text(x, up + 10, f'{sum(saved.values()):.0f}k\n{misses/len(seeds):.1f} misses', ha='center',
                    va='bottom', fontsize=6, linespacing=1.1)
        ax.axhline(0, color='k', lw=.6)
        ax.set_xticks(range(len(arms)), [ARM_NAMES[a].replace(' ', '\n', 1) for a in arms], fontsize=6.5)
        ax.set_title(title, fontsize=7)
    axes[0].set_ylim(top=1400)
    axes[0].set_ylabel('tokens saved against fixed inline\n(thousands per episode, mean of 5 seeds)')
    handles = [plt.matplotlib.patches.Patch(color=shades[v], label=f'context {v}') for v in VARIANTS]
    fig.legend(handles=handles, loc='lower center', ncol=6, frameon=False, bbox_to_anchor=(.5, -.06), fontsize=6.5)
    fig.tight_layout(rect=(0, .06, 1, 1))
    fig.savefig(out / f'se-savings.{fmt}', bbox_inches='tight')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='docs/seams2027/figures')
    parser.add_argument('--format', default='pdf')
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for make in (fig_opportunity, fig_timeline, fig_tradeoff, fig_pilots, fig_round_trip, fig_quota, fig_limit_sweep,
                 fig_deadline_origin, fig_requests, fig_request_sizes,
                 fig_economy, fig_savings):
        make(out, args.format)
        print('wrote', make.__name__)


if __name__ == '__main__':
    main()
