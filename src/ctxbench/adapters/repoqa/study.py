"""Deterministic research inputs; target identities never enter router features."""
from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

from ctxbench.adaptive.types import Candidate, ContextFit, Provenance
from ctxbench.benchmark.models import TrialSpec

CONFIGURATIONS = ('inline-code-full', 'local-mcp-repoqa-ops')
SPLIT_SEED = 20260929
EPISODE_SEEDS = (20261001, 20261002, 20261003)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def tree_hash(root: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        hasher.update(path.relative_to(root).as_posix().encode())
        hasher.update(b'\0')
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(65536), b''):
                hasher.update(chunk)
    return hasher.hexdigest()


def pair_trials(trials: list[TrialSpec]) -> dict[tuple, dict[str, TrialSpec]]:
    pairs = defaultdict(dict)
    ids = set()
    for trial in trials:
        if trial.trialId in ids or trial.configurationId not in CONFIGURATIONS:
            raise ValueError('duplicate trial or unexpected configuration')
        ids.add(trial.trialId)
        key = (trial.taskId, trial.instanceId, trial.provider, trial.modelId,
               trial.modelName, trial.repeatIndex)
        if trial.configurationId in pairs[key]:
            raise ValueError('duplicate candidate')
        pairs[key][trial.configurationId] = trial
    for pair in pairs.values():
        if set(pair) != set(CONFIGURATIONS):
            raise ValueError('missing candidate')
        a, b = (pair[c] for c in CONFIGURATIONS)
        for field in ('dataset', 'taskStatement', 'taskTemplate', 'taskTags', 'validationType',
                      'validationConfig', 'contextBlocks', 'parameters', 'params'):
            if getattr(a, field) != getattr(b, field):
                raise ValueError(f'unpaired answering setting: {field}')
        if (a.strategy, a.representation, b.strategy, b.representation) != ('inline', 'code', 'local_mcp', 'json'):
            raise ValueError('unexpected candidate treatment')
    if not pairs or len({k[2:5] for k in pairs}) != 1:
        raise ValueError('exactly one provider/model is required')
    return dict(pairs)


def split_targets(index: list[dict]) -> dict:
    groups = defaultdict(set)
    variants = defaultdict(set)
    for item in index:
        groups[item['normalizedLanguage']].add(item['baseId'])
        variants[item['baseId']].add(item['requestedContextTokens'])
    if any(v != {2048, 4096, 8192, 16384} for v in variants.values()):
        raise ValueError('each target must contain all four variants')
    rng = random.Random(SPLIT_SEED)
    calibration = [rng.choice(sorted(groups[language])) for language in sorted(groups)]
    return {'seed': SPLIT_SEED, 'calibration': calibration,
            'heldOut': sorted(set(variants) - set(calibration))}


def ordered_workload(index: list[dict], targets: list[str], seed: int) -> list[dict]:
    bins = defaultdict(list)
    for item in index:
        if item['baseId'] in targets:
            bins[item['requestedContextTokens']].append(item)
    rng = random.Random(seed)
    for size in sorted(bins):
        bins[size].sort(key=lambda x: x['instanceId'])
        rng.shuffle(bins[size])
    if len(bins) != 4 or len({len(v) for v in bins.values()}) != 1:
        raise ValueError('workload requires balanced variants')
    # Every phase boundary is divisible by four. Each block contains each size once.
    result = []
    for i in range(len(next(iter(bins.values())))):
        block = [bins[size][i] for size in sorted(bins)]
        rng.shuffle(block)
        result.extend(block)
    return [{'requestId': item['instanceId'], 'instanceId': item['instanceId'],
             'target': item['baseId'], 'language': item['normalizedLanguage'],
             'variant': f"{item['requestedContextTokens'] // 1024}k"}
            for item in result]


def initial_budget(trial, adapter, *, context_limit: int, output_reservation: int,
                   tokenizer=None, serialization_allowance: int = 256) -> Candidate:
    """Budget the actual initial strategy prompt and operation definitions.

    Byte count is a conservative token upper bound when no local tokenizer is
    supplied. The allowance covers provider serialization; tool-loop growth is
    intentionally not predicted by this preflight.
    """
    from ctxbench.ai.strategies.inline import DEFAULT_SYSTEM_INSTRUCTION
    from ctxbench.ai.strategies.local_mcp import DEFAULT_OPERATION_SYSTEM_INSTRUCTION
    from ctxbench.runtime.runtime import _context_to_text

    if context_limit <= 0 or output_reservation <= 0 or serialization_allowance < 0:
        raise ValueError('explicit positive context limit and output reservation required')
    if trial.strategy == 'inline':
        context = _context_to_text(adapter.get_context(trial.instanceId, trial.taskId, trial.representation).content)
        prompt = f'# Context:\n{context}\n\n# Task:\n{trial.taskStatement}\n'
        system, schemas = DEFAULT_SYSTEM_INSTRUCTION, ''
    else:
        instructions = adapter.dataset_instructions()
        prefix = f'# Dataset Instructions\n{instructions}\n\n' if instructions and instructions.strip() else ''
        prompt = f'{prefix}# Task:\n{trial.taskStatement}\n\n# Instance ID:\n{trial.instanceId}\n\n'
        system = DEFAULT_OPERATION_SYSTEM_INSTRUCTION
        tools = adapter.tool_provider(allowed_operations=trial.surfaceSpec['operations']).list_tools()
        schemas = json.dumps([tool.model_dump(mode='json') for tool in tools], sort_keys=True)
    parts = (system, prompt, schemas)
    tokens = sum(len(tokenizer(p)) if tokenizer else len(p.encode('utf-8')) for p in parts)
    provenance = Provenance.DERIVED if tokenizer else Provenance.ESTIMATED
    return Candidate(trial.configurationId, True,
                     ContextFit(tokens + serialization_allowance, output_reservation, context_limit, provenance))
