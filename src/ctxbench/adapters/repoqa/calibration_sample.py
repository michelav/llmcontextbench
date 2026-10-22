"""Stratified, weighted calibration instances from a pool's class labels (`selection.json`).

Per size and class, up to `per_class` calibration-split instances, drawn seeded with languages
round-robin; strata with fewer instances are taken whole. Weights restore the evaluation split's
class mix within each size and make the sizes equally frequent, so weighted calibration means
estimate the workload the routers will see (the baseline's instance-split weights).

    python -m ctxbench.adapters.repoqa.calibration_sample SELECTION OUT_DIR --per-class 12 --seed 2027

writes OUT_DIR/calibration.json (entries {"instance", "weight"}) and OUT_DIR/evaluation.json (every
evaluation-split instance) and prints the per-stratum counts.
"""
import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

CLASSES = ('isolated', 'intermediate', 'contested')


def _round_robin(rng, entries, count):
    by_language = defaultdict(list)
    for entry in sorted(entries, key=lambda e: e['instance']):
        by_language[entry['language']].append(entry)
    for group in by_language.values():
        rng.shuffle(group)
    languages, chosen = sorted(by_language), []
    while len(chosen) < count:
        for language in languages:
            if by_language[language] and len(chosen) < count:
                chosen.append(by_language[language].pop())
    return chosen


def calibration_sample(selection, *, per_class, seed):
    """Returns (calibration entries with weights, evaluation instance IDs, counts per stratum)."""
    strata, natural = defaultdict(list), defaultdict(int)
    for entry in selection:
        if entry['class'] not in CLASSES:
            raise ValueError(f"unknown class {entry['class']}")
        key = (entry['size'], entry['class'])
        if entry['split'] == 'calibration':
            strata[key].append(entry)
        elif entry['split'] == 'evaluation':
            natural[key] += 1
        else:
            raise ValueError(f"unknown split {entry['split']}")
    sizes = sorted({size for size, _ in strata} | {size for size, _ in natural})
    calibration, counts = [], {}
    for size in sizes:
        total = sum(natural[(size, c)] for c in CLASSES)
        if not total:
            raise ValueError(f'no evaluation instances at size {size}')
        for klass in CLASSES:
            share = natural[(size, klass)]/total
            if share and not strata[(size, klass)]:
                raise ValueError(f'no calibration instances for {klass} at size {size}')
            rng = random.Random(f'{seed}:{size}:{klass}')
            chosen = _round_robin(rng, strata[(size, klass)], min(per_class, len(strata[(size, klass)])))
            counts[f'{size // 1024}k/{klass}'] = len(chosen)
            # Each size weighs 1 in total; within it, each class weighs its evaluation share.
            calibration += [{'instance': e['instance'], 'weight': share/len(chosen)} for e in chosen if share]
    evaluation = sorted(e['instance'] for e in selection if e['split'] == 'evaluation')
    return sorted(calibration, key=lambda e: e['instance']), evaluation, counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('selection', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--per-class', type=int, required=True)
    parser.add_argument('--seed', type=int, required=True)
    args = parser.parse_args(argv)
    calibration, evaluation, counts = calibration_sample(json.loads(args.selection.read_text()),
                                                         per_class=args.per_class, seed=args.seed)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'calibration.json').write_text(json.dumps(calibration, indent=1) + '\n')
    (args.output / 'evaluation.json').write_text(json.dumps(evaluation, indent=1) + '\n')
    print(json.dumps({'calibration': len(calibration), 'evaluation': len(evaluation), 'strata': counts}, indent=1))


if __name__ == '__main__':
    main()
