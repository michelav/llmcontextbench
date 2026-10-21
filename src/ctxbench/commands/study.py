"""Study commands; provider execution is explicit."""
import json
import sys


def register_study_commands(parser):
    sub = parser.add_subparsers(dest='study_command', required=True)
    baseline = sub.add_parser('baseline').add_subparsers(dest='baseline_command', required=True)
    prepare = baseline.add_parser('prepare', help='Prepare reusable calibration episodes')
    prepare.add_argument('--definition', required=True)
    prepare.add_argument('--output', required=True)
    for name in ('execute', 'freeze'):
        command = baseline.add_parser(name)
        command.add_argument('--prepared', required=True)
        if name == 'execute':
            command.add_argument('--resume', action='store_true')
            command.add_argument('--retry-uncertain', action='store_true')
            command.add_argument('--seed', type=int, help='Run only the episodes of this seed (one session)')
    for command in baseline.choices.values():
        command.set_defaults(func=study_command)
    prepare = sub.add_parser('prepare', help='Bind a declarative study to a frozen baseline')
    prepare.add_argument('--definition', required=True)
    prepare.add_argument('--output', required=True)
    episode = sub.add_parser('episode', help='Run one provider-backed study episode')
    episode.add_argument('--prepared', required=True)
    episode.add_argument('--policy', required=True)
    episode.add_argument('--scenario', required=True)
    episode.add_argument('--seed', type=int, required=True)
    episode.add_argument('--repeat', type=int, required=True)
    episode.add_argument('--resume', action='store_true')
    episode.add_argument('--retry-uncertain', action='store_true')
    status = sub.add_parser('status', help='Inspect planned and completed episodes')
    status.add_argument('path')
    analyze = sub.add_parser('analyze', help='Analyze saved episodes without provider calls')
    analyze.add_argument('path')
    analyze.add_argument('--bootstrap-replicates', type=int, default=1000)
    analyze.add_argument('--bootstrap-seed', type=int, default=42)
    replay = sub.add_parser('replay', help='Provider-free replay of policies over calibration observations')
    source = replay.add_mutually_exclusive_group(required=True)
    source.add_argument('--prepared', help='Prepared study supplying plan and workload features')
    source.add_argument('--baseline', help='Frozen baseline (read-only; no source verification)')
    replay.add_argument('--grid', required=True, help='Replay grid JSON (schemaVersion 1)')
    replay.add_argument('--output', help='Write the replay report to this JSON file')
    replay.add_argument('--replicates', type=int)
    counterfactual = sub.add_parser('counterfactual',
                                    help='Pair two fixed arms of a completed study as a primary/fallback cascade')
    counterfactual.add_argument('--study-dir', required=True)
    counterfactual.add_argument('--primary', required=True, help='Policy name of the primary fixed arm')
    counterfactual.add_argument('--fallback', required=True, help='Policy name of the fallback fixed arm')
    for command in (status, analyze):
        command.add_argument('--allow-source-drift', action='store_true',
                             help='Read-only: tolerate changed measurement sources; reports list them as sourceDrift')
    for command in (status, analyze, replay):
        command.add_argument('--path-map', action='append', metavar='OLD=NEW',
                             help='Read-only: find recorded absolute paths under OLD at NEW (repeatable; longest OLD wins)')
    for command in sub.choices.values():
        if command.get_default('func') is None and command.prog.rsplit(' ', 1)[-1] != 'baseline':
            command.set_defaults(func=study_command)


def study_command(args):
    from ctxbench.studies import baseline, study
    options = vars(args).copy()
    baseline_operation = options.pop('baseline_command', None)
    operation = options.pop('study_command')
    for key in ('command', 'func'):
        options.pop(key, None)
    if baseline_operation is not None:
        target, operation = baseline, baseline_operation
    elif operation in ('replay', 'counterfactual'):
        from ctxbench.studies import replay as target
        operation = 'replay' if operation == 'replay' else 'counterfactual_cascade'
    else:
        target = study
    if operation in ('execute', 'episode'):
        print('Provider execution may spend API tokens; review the prepared matrix before running.', file=sys.stderr)
    print(json.dumps(getattr(target, operation)(**options), indent=2))
    return 0
