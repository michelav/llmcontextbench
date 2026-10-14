"""New policy options must default to v1 behaviour: recorded v1 decisions replay exactly."""
from pathlib import Path

import pytest

from ctxbench.adaptive.recovery import sealed_read
from ctxbench.adaptive.study_policy import Controller
from ctxbench.adaptive.study_runner import load_packets

V1_STUDIES = [Path('studies') / f'repoqa-long64-{name}' for name in ('latency', 'budget', 'reliability')]


@pytest.mark.parametrize('root', V1_STUDIES, ids=lambda p: p.name)
def test_v1_decisions_replay_identically(root):
    if not (root / 'prepared.json').is_file():
        pytest.skip('v1 study artifacts are not present in this checkout')
    plan = sealed_read(root / 'prepared.json')
    replayed = 0
    for episode in plan['episodes']:
        packets = load_packets(root / 'episodes' / episode['id'])
        controller = Controller(plan, episode)
        for index, packet in enumerate(packets):
            recorded = packet['selection']
            assert controller.decide(index) == recorded, (episode['policyName'], index)
            controller.observe(packet['observation'])
            replayed += 1
    assert replayed
