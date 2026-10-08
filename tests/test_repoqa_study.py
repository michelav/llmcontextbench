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


def test_pair_validation_and_actual_prompt_budget(tmp_path):
    from ctxbench.adapters.repoqa.package import RepoQADatasetAdapter
    from ctxbench.adapters.repoqa.study import initial_budget, pair_trials
    from ctxbench.benchmark.models import DatasetProvenance, Experiment
    from ctxbench.benchmark.runspec_generator import generate_runspecs
    from ctxbench.ai.strategies.inline import DEFAULT_SYSTEM_INSTRUCTION
    root = Path('tests/fixtures/repoqa_tools_dataset').resolve()
    adapter = RepoQADatasetAdapter(root)
    experiment = Experiment.model_validate(json.loads(Path('tests/fixtures/repoqa_surface_experiment.json').read_text()))
    trials = generate_runspecs(experiment, tmp_path, adapter,
                              DatasetProvenance(id='ctxbench/repoqa', version='fixture', materialized_path=str(root)))
    assert len(pair_trials(trials)) == 1
    with pytest.raises(ValueError, match='missing'):
        pair_trials(trials[:1])
    with pytest.raises(ValueError, match='duplicate'):
        pair_trials(trials + trials[:1])
    changed = trials[1].model_copy(update={'params': {'different': True}})
    with pytest.raises(ValueError, match='answering setting'):
        pair_trials([trials[0], changed])
    trial = trials[0]
    context = adapter.get_context(trial.instanceId, trial.taskId, trial.representation).content
    text = DEFAULT_SYSTEM_INSTRUCTION + f'# Context:\n{context}\n\n# Task:\n{trial.taskStatement}\n'
    tokens = len(text.encode()) + 256
    candidate = initial_budget(trial, adapter, context_limit=tokens + 100, output_reservation=100)
    assert candidate.context_fit.input_tokens == tokens
    assert candidate.eligible
    assert not initial_budget(trial, adapter, context_limit=tokens + 99, output_reservation=100).eligible
    assert initial_budget(trials[1], adapter, context_limit=200000, output_reservation=100).eligible


def test_tokenizer_count_with_allowance_keeps_estimated_provenance(tmp_path):
    from ctxbench.adapters.repoqa.package import RepoQADatasetAdapter
    from ctxbench.adapters.repoqa.study import initial_budget
    from ctxbench.adaptive.types import Provenance
    from ctxbench.benchmark.models import DatasetProvenance, Experiment
    from ctxbench.benchmark.runspec_generator import generate_runspecs
    root = Path('tests/fixtures/repoqa_tools_dataset').resolve()
    adapter = RepoQADatasetAdapter(root)
    experiment = Experiment.model_validate(json.loads(Path('tests/fixtures/repoqa_surface_experiment.json').read_text()))
    trial = generate_runspecs(experiment, tmp_path, adapter,
                             DatasetProvenance(id='ctxbench/repoqa', version='fixture', materialized_path=str(root)))[0]
    options = dict(context_limit=200000, output_reservation=100, tokenizer=lambda text: list(text))
    assert initial_budget(trial, adapter, **options).context_fit.provenance == Provenance.ESTIMATED
    assert initial_budget(trial, adapter, serialization_allowance=0, **options).context_fit.provenance == Provenance.DERIVED
