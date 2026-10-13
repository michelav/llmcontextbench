"""Provider-free streaming audit; historical payload keys are evidence, not runtime inference."""
import argparse
from collections import Counter
import json
from pathlib import Path


def audit(root):
    statuses, failures, operation_flags = Counter(), Counter(), Counter()
    files = sorted(Path(root).rglob('responses.jsonl'))
    traces = 0
    for path in files:
        for line in path.open(encoding='utf-8'):
            row = json.loads(line)
            statuses[row['status']] += 1
            if row['status'] != 'success':
                error = row.get('errorMessage') or ''
                failures['step-limit' if 'exceeded max_steps=' in error else 'unknown'] += 1
            ref = row.get('traceRef')
            if not ref:
                continue
            trace_path = path.parent / ref
            if not trace_path.is_file():
                continue
            traces += 1
            trace = json.loads(trace_path.read_text())
            # Inspect one trace at a time; count the canonical tool-call records only.
            for call in trace.get('trace', {}).get('toolCalls', []):
                result = call.get('result')
                if isinstance(result, dict) and set(result) == {'error'}:
                    operation_flags[str(call.get('isError'))] += 1
    return {'responseFiles': len(files), 'responseBytes': sum(p.stat().st_size for p in files),
            'records': sum(statuses.values()), 'statuses': dict(statuses),
            'failedRequests': dict(failures), 'unknown': failures['unknown'],
            'tracesInspected': traces, 'errorOnlyPayloadFlags': dict(operation_flags)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root')
    print(json.dumps(audit(parser.parse_args().root), indent=2))
