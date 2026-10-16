"""SEAMS 2027 figures from the replay reports, the pilots and the S-E' live study (no provider calls).

Usage: python tools/seams/make_figures.py [--out docs/seams2027/figures] [--format pdf]

Replay results are labelled `estimated`; live results come from `analysis.json` and decision logs.
"""
import argparse, json, os
os.environ.setdefault("SOURCE_DATE_EPOCH", "0")  # reproducible PDF metadata
from pathlib import Path
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


ROUTER_MARKERS = {'frozen': 's', 'v1': '^', 'v2': 'o'}
FIXED_MARKERS = {'inline': '+', 'direct': 'x'}


def fig_requests(out, fmt, seed=301):
    """Live S-E', inline delayed, one seed: every request of each arm in one plot; router misses coloured by size bin."""
    prep, rows, _ = se3.load(LIVE)
    bins = {rid: r['sizeBin'] for rid, r in prep['requests'].items()}
    limit = se3.LIMIT/1000
    arms = list(FIXED_MARKERS) + list(ROUTER_MARKERS)
    offsets = dict(zip(arms, (-.3, -.15, 0, .15, .3)))
    fig, ax = plt.subplots(figsize=(7.0, 3.4))
    ax.axvspan(30.5, 60.5, color='0.93', zorder=0)
    for arm in arms:
        episode = rows[(arm, 'inline-degraded', seed)]
        for i, r in sorted(episode.items()):
            x, y = i + offsets[arm], r['durationMs']/1000
            if arm in FIXED_MARKERS:
                ax.scatter(x, y, s=10, marker=FIXED_MARKERS[arm], color='0.75', linewidths=.6, zorder=2)
            elif y > limit:
                ax.scatter(x, y, s=16, marker=ROUTER_MARKERS[arm], color=BIN_COLORS[bins[r['requestId']]],
                           edgecolors='k', linewidths=.3, zorder=4)
            else:
                ax.scatter(x, y, s=12, marker=ROUTER_MARKERS[arm], facecolors='none', edgecolors='0.55',
                           linewidths=.5, zorder=3)
    ax.axhline(limit, color='k', lw=1, ls='--', zorder=5)
    ax.set_xlim(0, 97)
    ax.set_xlabel(f'request position in the episode (seed {seed})')
    ax.set_ylabel('request latency (s)')
    missed = {arm: [sum(rows[(arm, 'inline-degraded', seed)][i]['durationMs'] > se3.LIMIT
                        for i in range(lo, hi + 1)) for lo, hi in se3.PHASES] for arm in arms}
    names = {'inline': 'fixed inline', 'direct': 'fixed MCP direct', 'frozen': 'frozen router',
             'v1': 'adaptive v1', 'v2': 'adaptive v2'}
    label = lambda arm: f"{names[arm]} ({'/'.join(map(str, missed[arm]))})"
    handles = [plt.Line2D([], [], ls='', marker=m, mfc='none', mec='0.4', label=label(a)) for a, m in ROUTER_MARKERS.items()]
    handles += [plt.Line2D([], [], ls='', marker=m, color='0.6', label=label(a)) for a, m in FIXED_MARKERS.items()]
    handles += [plt.matplotlib.patches.Patch(color=c, label=f'router miss, {b} context') for b, c in BIN_COLORS.items()]
    handles += [plt.Line2D([], [], color='k', ls='--', label='latency limit 7 s'),
                plt.matplotlib.patches.Patch(color='0.93', label='requests 31-60: inline +9 s')]
    ax.legend(handles=handles, frameon=False, ncol=3, loc='upper left', bbox_to_anchor=(0, -.18), fontsize=6.5,
              title='arm (misses in requests 1-30 / 31-60 / 61-96); hollow = met the limit', title_fontsize=6.5)
    fig.tight_layout()
    fig.savefig(out / f'se-requests.{fmt}', bbox_inches='tight')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='docs/seams2027/figures')
    parser.add_argument('--format', default='pdf')
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for make in (fig_opportunity, fig_timeline, fig_tradeoff, fig_pilots, fig_round_trip, fig_quota, fig_limit_sweep,
                 fig_deadline_origin, fig_requests):
        make(out, args.format)
        print('wrote', make.__name__)


if __name__ == '__main__':
    main()
