#!/usr/bin/env python3
"""Compatibility entry point for the RepoQA adaptation study."""
import argparse
import json
from ctxbench.adapters.repoqa.workflow import ARMS
from ctxbench.adapters.repoqa.study import EPISODE_SEEDS
from ctxbench.adaptive.calibration import DELAYS_MS


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    prepare_parser = sub.add_parser('prepare')
    prepare_parser.add_argument('--experiment', default='experiment.repoqa-adaptive.json')
    prepare_parser.add_argument('--context-limit', type=int, required=True)
    prepare_parser.add_argument('--output-reservation', type=int, required=True)
    prepare_parser.add_argument('--output', required=True)
    for operation in ('calibrate', 'episode', 'freeze'):
        p = sub.add_parser(operation)
        p.add_argument('--prepared', required=True)
        p.add_argument('--output', required=True)
        if operation == 'freeze':
            p.add_argument('--application-slo-ms', type=float)
        else:
            p.add_argument('--resume', action='store_true')
            p.add_argument('--retry-uncertain', action='store_true')
            p.add_argument('--seed', type=int, choices=EPISODE_SEEDS, default=EPISODE_SEEDS[0])
            if operation == 'episode':
                p.add_argument('--policy', choices=ARMS + ('all',), required=True)
                p.add_argument('--scenario', choices=('stationary', 'degradation-recovery'), required=True)
            else:
                p.add_argument('--delay-ms', type=int, choices=(0,) + DELAYS_MS, default=0)
    p = sub.add_parser('analyze')
    p.add_argument('--output', required=True)
    p.add_argument('--bootstrap-replicates', type=int, default=10000)
    args = parser.parse_args(argv)
    from ctxbench.adapters.repoqa import workflow
    options = vars(args).copy()
    operation = options.pop('operation')
    if operation in ('calibrate', 'episode'):
        import sys
        print('Provider execution spends API tokens, including multiple local-MCP steps. '
              'Review the prepared/frozen cost projections before running.', file=sys.stderr)
    result = getattr(workflow, operation)(**options)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
