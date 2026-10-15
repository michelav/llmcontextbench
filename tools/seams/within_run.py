"""Within-run latency variation of a frozen baseline's calibration episodes.

Joins the frozen observations with response start times and prints, per configuration and
wall-clock window: median latency, the share above a threshold, and model time per output
token (from `metricsSummary`, provider-reported durations measured by the runtime). Use it
to tell between-run drift from transient slow periods inside one calibration run.
"""
import argparse
import glob
import json
import statistics as st
from datetime import datetime
from pathlib import Path


def load(base):
    observations = json.loads((Path(base)/'frozen.json').read_text())['payload']['observations']
    responses = {}
    for path in glob.glob(f'{base}/episodes/*/responses.jsonl'):
        with open(path) as handle:
            for line in handle:
                row = json.loads(line)
                started = datetime.fromisoformat(row['timing']['startedAt'].replace('Z', '+00:00')).timestamp()
                responses[row['trialId']] = (started, row.get('metricsSummary') or {})
    rows = [dict(o, started=responses[o['trialId']][0], metrics=responses[o['trialId']][1])
            for o in observations if o['trialId'] in responses]
    origin = min(r['started'] for r in rows)
    for r in rows:
        r['minute'] = (r['started']-origin)/60
    return rows


def windows(rows, minutes, threshold_ms):
    configurations = sorted({r['configuration'] for r in rows})
    end = max(r['minute'] for r in rows)
    result = []
    start = 0
    while start <= end:
        cells = {}
        for cid in configurations:
            sel = [r for r in rows if r['configuration'] == cid and start <= r['minute'] < start+minutes]
            if not sel:
                continue
            per_token = [r['metrics']['modelDurationMs']/r['metrics']['outputTokens'] for r in sel
                         if r['metrics'].get('modelDurationMs') and r['metrics'].get('outputTokens')]
            cells[cid] = {'requests': len(sel), 'medianLatencyMs': round(st.median(r['durationMs'] for r in sel)),
                          'aboveThreshold': round(sum(r['durationMs'] > threshold_ms for r in sel)/len(sel), 3),
                          'modelMsPerOutputToken': round(st.median(per_token), 1) if per_token else None}
        result.append({'fromMinute': start, 'toMinute': start+minutes, 'configurations': cells})
        start += minutes
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('baseline', nargs='+', help='Baseline directories (containing frozen.json and episodes/)')
    parser.add_argument('--minutes', type=int, default=15)
    parser.add_argument('--threshold-ms', type=int, default=10000)
    parser.add_argument('--output', help='Write all windows as JSON')
    args = parser.parse_args()
    report = {}
    for base in args.baseline:
        report[base] = windows(load(base), args.minutes, args.threshold_ms)
        print(f'== {base}: median latency s / share > {args.threshold_ms/1000:g} s / model ms per output token')
        for window in report[base]:
            cells = '  '.join(f"{cid}: {c['medianLatencyMs']/1000:.1f}/{c['aboveThreshold']:.0%}/{c['modelMsPerOutputToken']}"
                              for cid, c in window['configurations'].items())
            print(f"{window['fromMinute']:>3}-{window['toMinute']:<3} {cells}")
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
