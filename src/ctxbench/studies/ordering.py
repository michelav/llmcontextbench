"""Workload orders: the same requests in a different sequence, so arms see identical requests."""
import random


def ordered(workload, order, seed, scenario):
    """Reorder `workload` (rows from `ordered_workload`) by phases of sizes; every request is used once.

    A phase's positions draw, in seeded random order, unused requests whose size bin or nominal
    size (`variant`, e.g. `64k`) is listed. Returns instance IDs."""
    rng = random.Random(f'order:{seed}:{scenario}')
    remaining = list(workload)
    result = []
    for phase in order['phases']:
        sizes = set(phase['sizes'])
        while len(result) < phase['lastRequest']:
            matching = [row for row in remaining if row['sizeBin'] in sizes or row['variant'] in sizes]
            if not matching:
                raise ValueError(f"workload order for {scenario} runs out of {sorted(sizes)} requests "
                                 f"at position {len(result)+1}")
            row = rng.choice(matching)
            remaining.remove(row)
            result.append(row['instanceId'])
    if remaining:
        raise ValueError(f'workload order for {scenario} leaves {len(remaining)} requests unused')
    return result


def order_phases(order):
    """Phase ranges of an order, with their disturbance flag."""
    phases, start = [], 1
    for phase in order['phases']:
        phases.append({'firstRequest': start, 'lastRequest': phase['lastRequest'],
                       'disturbance': phase.get('disturbance', False)})
        start = phase['lastRequest']+1
    return phases
