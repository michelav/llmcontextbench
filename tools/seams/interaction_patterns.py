"""Interaction patterns and per-call latency of a frozen baseline's calibration episodes.

Reads the execution traces of the baseline episodes and prints, per configuration:
latency split into model, tool and harness time (measured); model calls per request;
per-call latency by position; tool-call sequences; latency by number of model calls;
and a least-squares fit of model-call duration on uncached input, cached input and
output tokens (provider-reported usage; the fit is a derived description, not a model
of the provider).
"""
import argparse
import collections
import glob
import json
import statistics as st
from pathlib import Path


def _responses(raw):
    for item in raw if isinstance(raw, list) else [raw]:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except ValueError:
                continue
        if isinstance(item, dict):
            yield item


def load(base):
    observations = {o['trialId']: o for o in json.loads((Path(base)/'frozen.json').read_text())['payload']['observations']}
    trials = []
    for path in glob.glob(f'{base}/episodes/*/traces/executions/*.json'):
        trace = json.loads(Path(path).read_text())
        observation = observations.get(trace['trialId'])
        if observation is None:
            continue
        events = trace['trace']['aiTrace']['events']
        calls = []
        for response in _responses(trace['trace'].get('rawResponse') or []):
            usage = response.get('usage') or {}
            calls.append({'input': usage.get('input_tokens', 0),
                          'cached': (usage.get('input_tokens_details') or {}).get('cached_tokens', 0),
                          'output': usage.get('output_tokens', 0),
                          'functionCalls': sum(1 for x in response.get('output', []) if x.get('type') == 'function_call')})
        durations = [e['duration_ms'] for e in events if e['type'] == 'model.generate']
        if len(durations) == len(calls):
            for call, duration in zip(calls, durations):
                call['durationMs'] = duration
        trials.append({'configuration': observation['configuration'], 'sizeBin': observation['sizeBin'],
                       'durationMs': observation['durationMs'], 'status': observation['status'],
                       'modelMs': durations,
                       'toolMs': sum(e.get('duration_ms') or 0 for e in events if e['type'].endswith('tool_result')),
                       'tools': [e['metadata'].get('tool_name') for e in events if e['type'].endswith('tool_call')],
                       'calls': calls})
    return trials


def summarize(trials):
    report = {}
    by = collections.defaultdict(list)
    for trial in trials:
        by[trial['configuration']].append(trial)
    for cid, rows in sorted(by.items()):
        multi = [r for r in rows if len(r['modelMs']) > 1]
        sequences = collections.Counter(' > '.join(r['tools']) for r in rows)
        by_calls = collections.defaultdict(list)
        for r in rows:
            by_calls[len(r['modelMs'])].append(r['durationMs'])
        report[cid] = {
            'requests': len(rows),
            'medianLatencyMs': st.median(r['durationMs'] for r in rows),
            'meanModelCalls': round(st.mean(len(r['modelMs']) for r in rows), 2),
            'medianModelMs': st.median(sum(r['modelMs']) for r in rows),
            'medianToolMs': st.median(r['toolMs'] for r in rows),
            'medianHarnessMs': st.median(r['durationMs']-sum(r['modelMs'])-r['toolMs'] for r in rows),
            'medianCallMs': {'first': st.median(r['modelMs'][0] for r in rows if r['modelMs']),
                             'middle': st.median([m for r in rows for m in r['modelMs'][1:-1]] or [float('nan')]),
                             'last': st.median([r['modelMs'][-1] for r in multi] or [float('nan')])},
            'parallelToolCallRequests': sum(any(c['functionCalls'] > 1 for c in r['calls']) for r in rows),
            'toolSequences': dict(sequences.most_common()),
            'medianLatencyByModelCalls': {k: st.median(v) for k, v in sorted(by_calls.items())},
            'requestsByModelCalls': {k: len(v) for k, v in sorted(by_calls.items())},
        }
    return report


def fit(trials):
    """Least squares: seconds = a + b·uncached/1k + c·cached/1k + d·output/100."""
    import numpy as np
    rows = [c for t in trials for c in t['calls'] if 'durationMs' in c]
    x = np.array([[1, (c['input']-c['cached'])/1000, c['cached']/1000, c['output']/100] for c in rows])
    y = np.array([c['durationMs']/1000 for c in rows])
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    r2 = 1-((y-x@coef)**2).sum()/((y-y.mean())**2).sum()
    return {'calls': len(rows), 'fixedSeconds': round(coef[0], 3), 'perThousandUncachedInput': round(coef[1], 4),
            'perThousandCachedInput': round(coef[2], 4), 'perHundredOutput': round(coef[3], 3), 'r2': round(r2, 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('baseline', nargs='+', help='Baseline directories (containing frozen.json and episodes/)')
    parser.add_argument('--top', type=int, default=4, help='Tool sequences printed per configuration')
    parser.add_argument('--output', help='Write the full report as JSON')
    args = parser.parse_args()
    full = {}
    for base in args.baseline:
        trials = load(base)
        report, model = summarize(trials), fit(trials)
        full[base] = {'configurations': report, 'callFit': model}
        print(f'== {base}')
        print(f"call fit: {model['fixedSeconds']} s + {model['perThousandUncachedInput']} s/1k uncached + "
              f"{model['perThousandCachedInput']} s/1k cached + {model['perHundredOutput']} s/100 output "
              f"(R2 {model['r2']}, {model['calls']} calls)")
        for cid, r in report.items():
            calls = r['medianCallMs']
            print(f"{cid:24} latency {r['medianLatencyMs']/1000:.1f} s  calls {r['meanModelCalls']}  "
                  f"model {r['medianModelMs']/1000:.1f} s  tool {r['medianToolMs']/1000:.2f} s  harness {r['medianHarnessMs']/1000:.2f} s  "
                  f"call first/middle/last {calls['first']/1000:.2f}/{calls['middle']/1000:.2f}/{calls['last']/1000:.2f} s")
            if any(r['toolSequences']):
                for sequence, count in list(r['toolSequences'].items())[:args.top]:
                    print(f'    {count:4}  {sequence}')
                print(f"    latency by model calls: " + ', '.join(
                    f"{k}: {v/1000:.1f} s (n={r['requestsByModelCalls'][k]})" for k, v in r['medianLatencyByModelCalls'].items()))
    if args.output:
        Path(args.output).write_text(json.dumps(full, indent=2, default=float)+'\n')


if __name__ == '__main__':
    main()
