"""Seeded R3 workloads from an evaluation instance list and the pool's class labels (`selection.json`).

Per seed: a stationary sequence (S-A) with the five sizes equally frequent; a large-context burst
(S-L) of 32k-64k requests in a 2k-16k stream; a contested burst (S-C) that swaps contested
instances of the same size into the S-A sequence; and S-D, the S-A sequence itself (the slowdown is
a scenario effect). Each seed gets one burst placement, cycling through `placements`. Sizes are
drawn in shuffled blocks, one of each size per block, and instances uniformly within a size, so the
class mix is the evaluation split's.

    python -m ctxbench.adapters.repoqa.burst_workloads SELECTION EVALUATION OUT --seeds 1 2 3 \\
        --length 48 --burst 16 --placements 13 17 21

writes OUT (the study's `workloadFile`) and prints the definition's `scenarioSeeds` and `disturbances`.
"""
import argparse
import json
import random
from pathlib import Path

ALL_SIZES = ('2k', '8k', '16k', '32k', '64k')
NORMAL_SIZES, LARGE_SIZES = ('2k', '8k', '16k'), ('32k', '64k')


def _label(entry):
    return f"{entry['size'] // 1024}k"


def _sizes(rng, sizes, count):
    """`count` sizes in shuffled blocks with one of each size per block."""
    result = []
    while len(result) < count:
        block = list(sizes)
        rng.shuffle(block)
        result.extend(block)
    return result[:count]


def _draw(rng, pool, sizes, used):
    sequence = []
    for size in sizes:
        choices = [i for i in pool[size] if i not in used]
        if not choices:
            raise ValueError(f'the evaluation list runs out of {size} instances')
        instance = rng.choice(choices)
        used.add(instance)
        sequence.append(instance)
    return sequence


def burst_workloads(selection, evaluation, *, seeds, length, burst, placements):
    """Returns (workloads, scenarioSeeds, disturbances) for a study definition."""
    labels = {entry['instance']: entry for entry in selection}
    if missing := sorted(set(evaluation) - set(labels)):
        raise ValueError(f'evaluation instances without labels: {missing[:5]}')
    if len(set(evaluation)) != len(evaluation):
        raise ValueError('duplicate evaluation instances')
    if any(p < 1 or p+burst-1 > length for p in placements) or len(set(placements)) != len(placements):
        raise ValueError('burst placements must be distinct and fit the workload')
    pool, contested = {s: [] for s in ALL_SIZES}, {s: [] for s in ALL_SIZES}
    for instance in sorted(evaluation):
        size = _label(labels[instance])
        if size not in pool:
            raise ValueError(f'unsupported size {size}')
        pool[size].append(instance)
        if labels[instance]['class'] == 'contested':
            contested[size].append(instance)
    workloads, scenario_seeds, disturbances = {}, {}, {}
    for index, seed in enumerate(seeds):
        start = placements[index % len(placements)]
        window = range(start-1, start-1+burst)
        rng = random.Random(f'stationary:{seed}')
        stationary = _draw(rng, pool, _sizes(rng, ALL_SIZES, length), set())
        rng = random.Random(f'large-burst:{seed}')
        normal = iter(_sizes(rng, NORMAL_SIZES, length-burst))
        large = iter(_sizes(rng, LARGE_SIZES, burst))
        large_burst = _draw(rng, pool, [next(large) if i in window else next(normal) for i in range(length)], set())
        rng = random.Random(f'contested-burst:{seed}')
        swapped, used = list(stationary), set(stationary)
        for i in window:
            size = _label(labels[stationary[i]])
            if labels[stationary[i]]['class'] == 'contested':
                continue
            # At sizes with few contested instances a position keeps its request when none is left.
            choices = [c for c in contested[size] if c not in used]
            if choices:
                swapped[i] = rng.choice(choices)
                used.add(swapped[i])
        for name, sequence in ((f'S-L-{start}', large_burst), (f'S-C-{start}', swapped),
                               (f'S-D-{start}', stationary)):
            workloads.setdefault(name, {})[str(seed)] = sequence
            scenario_seeds.setdefault(name, []).append(seed)
            disturbances[name] = {'firstRequest': start, 'lastRequest': start+burst-1}
        workloads.setdefault('S-A', {})[str(seed)] = stationary
    return workloads, scenario_seeds, disturbances


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('selection', type=Path)
    parser.add_argument('evaluation', type=Path, help='JSON list of evaluation instance IDs')
    parser.add_argument('output', type=Path)
    parser.add_argument('--seeds', type=int, nargs='+', required=True)
    parser.add_argument('--length', type=int, required=True)
    parser.add_argument('--burst', type=int, required=True)
    parser.add_argument('--placements', type=int, nargs='+', required=True)
    args = parser.parse_args(argv)
    workloads, scenario_seeds, disturbances = burst_workloads(
        json.loads(args.selection.read_text()), json.loads(args.evaluation.read_text()),
        seeds=args.seeds, length=args.length, burst=args.burst, placements=args.placements)
    args.output.write_text(json.dumps(workloads, indent=1) + '\n')
    print(json.dumps({'scenarioSeeds': scenario_seeds, 'disturbances': disturbances}, indent=1))


if __name__ == '__main__':
    main()
