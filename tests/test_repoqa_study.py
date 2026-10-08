import json
from collections import Counter
from pathlib import Path

import pytest

from ctxbench.adapters.repoqa.study import digest, ordered_workload, split_targets, tree_hash


def test_real_split_and_balanced_order():
    index = json.loads(Path('datasets/repoqa/instances.index.json').read_text())
    split = split_targets(index)
    assert len(split['calibration']) == 4
    assert len(split['heldOut']) == 16
    schedule = ordered_workload(index, split['heldOut'], 20261001)
    assert len(schedule) == 64
    assert digest(schedule) == digest(ordered_workload(list(reversed(index)), split['heldOut'], 20261001))
    for phase in (schedule[:20], schedule[20:44], schedule[44:]):
        assert len(set(Counter(r['variant'] for r in phase).values())) == 1
    assert not set(split['calibration']) & {r['target'] for r in schedule}


def test_missing_variant_rejected():
    with pytest.raises(ValueError, match='four variants'):
        split_targets([{'normalizedLanguage': 'python', 'baseId': 'x', 'requestedContextTokens': 2048}])


def test_tree_hash_covers_content_and_paths(tmp_path):
    (tmp_path / 'a').write_text('x')
    before = tree_hash(tmp_path)
    (tmp_path / 'a').write_text('y')
    assert tree_hash(tmp_path) != before
