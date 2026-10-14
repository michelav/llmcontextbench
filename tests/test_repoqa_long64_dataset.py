import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / 'datasets/repoqa-2026-10-13-long64'
SIZES = {2048, 4096, 8192, 16384, 32768, 65536}


def test_long64_package_population_and_visible_needles():
    manifest = json.loads((ROOT / 'ctxbench.dataset.json').read_text())
    rows = json.loads((ROOT / 'instances.index.json').read_text())
    assert manifest['id'] == 'ctxbench/repoqa'
    assert manifest['datasetVersion'] == '2026-10-13-long64.1'
    assert manifest['generation']['baseNeedles'] == 20
    assert len(manifest['generation']['selection']) == 20
    assert len(rows) == len({row['instanceId'] for row in rows}) == 120
    groups = defaultdict(set)
    languages = Counter()
    for row in rows:
        groups[row['baseId']].add(row['requestedContextTokens'])
        if row['requestedContextTokens'] == 2048:
            languages[row['normalizedLanguage']] += 1
        assert row['needleName'] in (ROOT / row['contextDir'] / 'native_code_context.txt').read_text()
        assert row['actualCodeContextTokens'] > 0
        if row['requestedContextTokens'] == 65536:
            assert row['actualCodeContextTokens'] >= 0.95 * 65536
    assert len(groups) == 20
    assert all(sizes == SIZES for sizes in groups.values())
    assert languages == {'java': 5, 'python': 5, 'rust': 5, 'typescript': 5}
