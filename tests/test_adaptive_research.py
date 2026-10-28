import json

import pytest

from ctxbench.adaptive.research import (knowledge_diff, materialize_derivation, paired_differences,
                                        resample_knowledge, seeded_workload)


def test_seeded_workload_is_reproducible_and_excludes_lineage_groups():
    rows = [{"taskId": "t", "instanceId": str(i), "sourceGroup": f"g{i}"} for i in range(5)]
    assert seeded_workload(rows, size=3, seed=19, excluded_groups={"g0"}) == seeded_workload(
        rows, size=3, seed=19, excluded_groups={"g0"})
    assert all(row["sourceGroup"] != "g0" for row in seeded_workload(rows, size=4, seed=19,
                                                                       excluded_groups={"g0"}))
    with pytest.raises(ValueError, match="eligible coverage"):
        seeded_workload(rows, size=5, seed=19, excluded_groups={"g0"})


def test_resampling_is_seeded_estimated_and_requires_complete_coverage():
    observations = [{"candidateId": "m/a", "featureGroup": "small", "latencyMs": n}
                   for n in (1, 3, 5)]
    a = resample_knowledge(observations, candidates=["m/a"], feature_groups=["small"], replicates=8, seed=4)
    assert a == resample_knowledge(observations, candidates=["m/a"], feature_groups=["small"], replicates=8, seed=4)
    assert a["estimates"]["m/a|small"]["latencyMs"]["provenance"] == "estimated"
    with pytest.raises(ValueError, match="missing calibration coverage"):
        resample_knowledge(observations, candidates=["m/b"], feature_groups=["small"], replicates=2, seed=4)


def test_knowledge_diff_does_not_mutate_inputs():
    before = {"estimates": {"m/a|small": {"latencyMs": 3}}}
    after = {"estimates": {"m/a|small": {"latencyMs": 5}, "m/b|small": {"latencyMs": 2}}}
    snapshot = json.dumps((before, after), sort_keys=True)
    assert len(knowledge_diff(before, after)) == 2
    assert json.dumps((before, after), sort_keys=True) == snapshot


def test_materialized_derivation_preserves_source_tree(tmp_path):
    source = tmp_path / "base"
    source.mkdir()
    (source / "data.txt").write_text("base")
    destination = tmp_path / "derived"
    manifest = materialize_derivation(source, destination, dataset_id="ds-v2",
                                      selected_requests=[{"taskId": "t", "instanceId": "i"}])
    assert (source / "data.txt").read_text() == "base"
    assert (destination / "data.txt").read_text() == "base"
    assert json.loads((destination / "derivation.json").read_text()) == manifest


def test_paired_differences_report_only_complete_pairs():
    rows = [{"requestId": "r1", "arm": "a", "latencyMs": 2},
            {"requestId": "r1", "arm": "b", "latencyMs": 5},
            {"requestId": "r2", "arm": "a", "latencyMs": 4}]
    result = paired_differences(rows, metric="latencyMs", left="a", right="b")
    assert result["differences"] == [{"pair": "r1", "difference": 3}]
    assert result["pairedCount"] == 1 and result["scheduledPairs"] == 2 and result["coverage"] == 0.5
