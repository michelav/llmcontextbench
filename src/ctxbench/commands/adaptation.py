"""Experimental RepoQA command registration; workflow imports are deferred."""
from __future__ import annotations

import argparse
import json
import sys

from ctxbench.adapters.repoqa.study import ARMS, EPISODE_SEEDS
from ctxbench.adaptive.calibration import DELAYS_MS


def register_repoqa_commands(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest='operation', required=True)
    prepare_parser = sub.add_parser('prepare', help='Prepare a study without provider calls')
    prepare_parser.add_argument('--experiment', default='experiment.repoqa-adaptive.json')
    prepare_parser.add_argument('--context-limit', type=int, required=True)
    prepare_parser.add_argument('--output-reservation', type=int, required=True)
    prepare_parser.add_argument('--output', required=True)
    for operation in ('calibrate', 'episode', 'freeze'):
        description = ('Freeze calibration without provider calls' if operation == 'freeze'
                       else 'Execute configured providers; may spend API tokens')
        p = sub.add_parser(operation, help=description, description=description)
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
    p = sub.add_parser('analyze', help='Analyze saved episodes without provider calls')
    p.add_argument('--output', required=True)
    p.add_argument('--bootstrap-replicates', type=int, default=10000)
    for command in sub.choices.values():
        command.set_defaults(func=adaptation_command)


def adaptation_command(args: argparse.Namespace) -> int:
    from ctxbench.adapters.repoqa import workflow

    options = vars(args).copy()
    operation = options.pop('operation')
    for key in ('command', 'adaptation_command', 'func'):
        options.pop(key, None)
    if operation in ('calibrate', 'episode'):
        print('Provider execution spends API tokens, including multiple local-MCP steps. '
              'Review the prepared/frozen cost projections before running.', file=sys.stderr)
    result = getattr(workflow, operation)(**options)
    print(json.dumps(result, indent=2))
    return 0
