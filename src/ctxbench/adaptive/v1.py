"""Minimal adaptive plan inputs for the v1 benchmark lifecycle."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean
from time import sleep
from typing import Any

from ctxbench.benchmark.fingerprint import file_digest
from ctxbench.benchmark.models import TrialSpec
from ctxbench.benchmark.provisioning import validate_artifact_directory
from ctxbench.util.jsonl import read_jsonl
from ctxbench.util.fs import load_json, write_json
from ctxbench.util.jsonl import write_jsonl


def candidate_id(model_id: str | None, configuration_id: str) -> str:
    return f"{model_id or ''}/{configuration_id}"


def build_adaptive_plan(adaptation: dict[str, Any], trials: list[TrialSpec], dataset: object) -> tuple[dict, dict | None]:
    policy = adaptation.get("policy")
    workload = adaptation.get("workload")
    if not isinstance(policy, dict) or not isinstance(workload, list) or not workload:
        raise ValueError("Adaptive definition requires a policy and nonempty explicit workload")
    if trials and any(trial.repeatIndex != 1 for trial in trials):
        raise ValueError("Adaptive definitions currently require execution.repeats=1")
    configurations = sorted({candidate_id(t.modelId, t.configurationId) for t in trials})
    if policy.get("type") == "static":
        selected = _candidate(policy.get("candidate"))
        if selected not in configurations:
            raise ValueError("Static policy candidate must be selected in the experiment candidates")
    elif policy.get("type") == "threshold":
        if type(policy.get("latencyTargetMs")) not in (int, float) or policy["latencyTargetMs"] < 0:
            raise ValueError("Threshold policy requires a nonnegative latencyTargetMs")
        if "calibration" not in adaptation:
            raise ValueError("Threshold policy requires a separate static calibration run")
    else:
        raise ValueError("Adaptive policy type must be static or threshold")

    phases = _validate_phases(adaptation.get("phases", []), len(workload))
    planned = []
    seen_repeats: defaultdict[tuple[str, str], int] = defaultdict(int)
    for index, item in enumerate(workload, 1):
        if not isinstance(item, dict):
            raise ValueError("Adaptive workload entries must be objects")
        task_id, instance_id = item.get("taskId"), item.get("instanceId")
        if task_id not in dataset.list_task_ids() or instance_id not in dataset.list_instance_ids():
            raise ValueError(f"Adaptive workload request {index} is outside the selected dataset scope")
        seen_repeats[(task_id, instance_id)] += 1
        if seen_repeats[(task_id, instance_id)] > 1:
            raise ValueError("Adaptive workloads cannot repeat a task/instance pair in this slice")
        raw_features = dataset.request_features(instance_id, task_id)
        size_bin = item.get("sizeBin", raw_features.get("sizeBin", "small"))
        if size_bin not in {"small", "medium", "large"}:
            raise ValueError(f"Invalid sizeBin for adaptive request {index}")
        candidates = [t for t in trials if t.taskId == task_id and t.instanceId == instance_id]
        by_candidate = {candidate_id(t.modelId, t.configurationId): t for t in candidates}
        eligible = item.get("eligibleCandidates")
        if eligible is not None:
            if not isinstance(eligible, list):
                raise ValueError("eligibleCandidates must be a list of [modelId, configurationId] pairs")
            eligible_ids = {_candidate(value) for value in eligible}
            if not eligible_ids.issubset(by_candidate):
                raise ValueError(f"Adaptive request {index} eligibility references an unplanned candidate")
            by_candidate = {key: value for key, value in by_candidate.items() if key in eligible_ids}
        phase = next((p for p in phases if p["firstRequest"] <= index <= p["lastRequest"]), None)
        planned.append({
            "requestId": f"request-{index:06d}",
            "sequenceIndex": index,
            "taskId": task_id,
            "instanceId": instance_id,
            "sizeBin": size_bin,
            "phase": phase["name"] if phase else "default",
            "toolDelayMs": phase.get("toolDelayMs", 0) if phase else 0,
            "candidates": {key: value.trialId for key, value in sorted(by_candidate.items())},
            "rejectionReason": "no_eligible_candidate" if not by_candidate else None,
        })
    knowledge = None
    if policy["type"] == "threshold":
        knowledge = _load_calibration(adaptation["calibration"], trials, planned, dataset)
    return {"schemaVersion": 1, "policy": dict(policy), "candidateIds": configurations,
            "workload": planned, "phases": phases,
            "calibration": adaptation.get("calibration") if knowledge else None}, knowledge


def _load_calibration(path: str, trials: list[TrialSpec], workload: list[dict], dataset: object) -> dict:
    root = Path(path).resolve()
    manifest = validate_artifact_directory(root)
    evaluation = manifest.get("evaluation", {})
    if manifest.get("experimentKind", "benchmark") != "benchmark" or evaluation.get("enabled"):
        raise ValueError("Calibration source must be a static benchmark run without evaluation")
    target_dataset = trials[0].dataset if trials else None
    source_dataset = manifest.get("dataset", {})
    if target_dataset is None or source_dataset.get("id") != target_dataset.id:
        raise ValueError("Calibration source dataset must match the adaptive experiment dataset")
    responses_path = root / "responses.jsonl"
    if not responses_path.is_file():
        raise ValueError("Calibration source responses.jsonl is required")
    evaluation_requests = {(item["taskId"], item["instanceId"]) for item in workload}
    groups: defaultdict[tuple[str, str], list[dict[str, float]]] = defaultdict(list)
    possible = {candidate_id(t.modelId, t.configurationId) for t in trials}
    response_rows = read_jsonl(responses_path)
    if not response_rows:
        raise ValueError("Calibration source has no responses")
    source_trials_path = root / "trials.jsonl"
    source_trials = read_jsonl(source_trials_path) if source_trials_path.is_file() else []
    target_by_candidate = {candidate_id(t.modelId, t.configurationId): t for t in trials}
    source_by_candidate = {}
    for row in source_trials:
        cid = candidate_id(row.get("modelId"), str(row.get("configurationId", "")))
        if cid in possible:
            source_by_candidate.setdefault(cid, row)
    for cid, target in target_by_candidate.items():
        source = source_by_candidate.get(cid)
        if source is None:
            continue  # A candidate with no source trials will fail metric coverage below.
        comparable = ("provider", "model", "strategy", "representation", "configurationId", "params", "surfaceSpec")
        target_row = {"provider": target.provider, "model": target.modelName,
                      "strategy": target.strategy, "representation": target.representation,
                      "configurationId": target.configurationId, "params": target.params,
                      "surfaceSpec": target.surfaceSpec}
        if any(source.get(key) != target_row[key] for key in comparable):
            raise ValueError(f"Calibration candidate semantics differ for {cid}")
    for row in response_rows:
        request_key = (str(row.get("taskId", "")), str(row.get("instanceId", "")))
        if request_key in evaluation_requests:
            raise ValueError("Calibration/evaluation workload overlap is not allowed")
        cid = candidate_id(row.get("modelId"), str(row.get("configurationId", "")))
        if cid not in possible or row.get("status") != "success":
            continue
        features = dataset.request_features(request_key[1], request_key[0])
        size_bin = features.get("sizeBin", "small")
        if size_bin not in {"small", "medium", "large"}:
            raise ValueError("Calibration dataset returned invalid sizeBin")
        metrics = row.get("metricsSummary", {})
        duration = row.get("timing", {}).get("durationMs")
        tokens = metrics.get("totalTokens")
        groups[(cid, size_bin)].append({
            **({"latencyMs": float(duration)} if isinstance(duration, (int, float)) else {}),
            **({"totalTokens": float(tokens)} if isinstance(tokens, (int, float)) else {}),
        })
    required = {(cid, req["sizeBin"]) for req in workload for cid in req["candidates"]}
    estimates = {}
    for key in sorted(required):
        rows = groups.get(key, [])
        latency = [row["latencyMs"] for row in rows if "latencyMs" in row]
        tokens = [row["totalTokens"] for row in rows if "totalTokens" in row]
        if not latency:
            raise ValueError(f"Calibration has no successful latency metrics for {key[0]} / {key[1]}")
        estimates[f"{key[0]}|{key[1]}"] = {
            "latencyMs": mean(latency), "latencyObservationCount": len(latency),
            "totalTokens": mean(tokens) if tokens else None,
            "tokenObservationCount": len(tokens),
            "provenance": "derived",
        }
    return {"schemaVersion": 1, "source": str(root), "sourceManifestDigest": file_digest(root / "manifest.json"),
            "sourceResponsesDigest": file_digest(responses_path), "estimates": estimates}


def _candidate(value: Any) -> str:
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(part, str) and part for part in value):
        raise ValueError("candidate must be [modelId, configurationId]")
    return candidate_id(value[0], value[1])


def _validate_phases(phases: Any, workload_size: int) -> list[dict]:
    if not isinstance(phases, list):
        raise ValueError("phases must be an array")
    result, expected_start = [], 1
    for phase in phases:
        if not isinstance(phase, dict):
            raise ValueError("workload phases must be objects")
        name, first, last = phase.get("name"), phase.get("firstRequest"), phase.get("lastRequest")
        delay = phase.get("toolDelayMs", 0)
        if (not isinstance(name, str) or not name or type(first) is not int or type(last) is not int
                or first != expected_start or last < first or last > workload_size
                or type(delay) is not int or delay < 0):
            raise ValueError("phases must cover contiguous workload ranges with valid toolDelayMs")
        result.append({"name": name, "firstRequest": first, "lastRequest": last, "toolDelayMs": delay})
        expected_start = last + 1
    if result and expected_start != workload_size + 1:
        raise ValueError("phases must cover the complete workload")
    return result


def choose_candidate(plan: dict, request: dict, knowledge: dict | None) -> tuple[str | None, str]:
    candidates = request["candidates"]
    policy = plan["policy"]
    if not candidates:
        return None, "no_eligible_candidate"
    if policy["type"] == "static":
        cid = _candidate(policy["candidate"])
        return (cid, "static") if cid in candidates else (None, "static_candidate_ineligible")
    estimates = (knowledge or {}).get("estimates", {})
    eligible = []
    for cid in candidates:
        estimate = estimates.get(f"{cid}|{request['sizeBin']}", {})
        latency = estimate.get("latencyMs")
        if isinstance(latency, (int, float)):
            eligible.append((cid, float(latency), estimate.get("totalTokens")))
    if not eligible:
        return None, "no_calibrated_candidate"
    target = float(policy["latencyTargetMs"])
    within = [row for row in eligible if row[1] <= target]
    pool = within or eligible
    chosen = min(pool, key=lambda row: (float("inf") if row[2] is None else row[2], row[1], row[0])) if within else min(pool, key=lambda row: (row[1], row[0]))
    return chosen[0], "threshold"


class DelayedToolRuntime:
    """Add an explicit per-call delay while preserving runtime ownership."""
    def __init__(self, inner, delay_ms: int, sleeper=sleep):
        self.inner, self.delay_ms, self.sleeper = inner, delay_ms, sleeper

    def list_tools(self):
        return self.inner.list_tools()

    def call_tool(self, name, arguments):
        if self.delay_ms:
            self.sleeper(self.delay_ms / 1000)
        return self.inner.call_tool(name, arguments)

    def close(self):
        self.inner.close()


def load_adaptive_records(root: Path) -> list[dict]:
    directory = root / "adaptive-records"
    records = []
    if directory.exists():
        for path in sorted(directory.glob("request-*.json")):
            record = load_json(path)
            if not isinstance(record, dict) or record.get("schemaVersion") != 1:
                raise ValueError(f"Invalid adaptive request record: {path}")
            records.append(record)
    return records


def execute_adaptive(plan: dict, knowledge: dict | None, runspecs: list[TrialSpec], *,
                     root: Path, manifest: dict, force: bool, retry_uncertain: bool,
                     logger, progress: bool) -> int:
    """Serially select and execute one candidate per explicit request."""
    from ctxbench.commands.execute import _execute_durable, _latest_attempt
    from ctxbench.benchmark.execution_records import attempts_for_trial

    by_id = {trial.trialId: trial for trial in runspecs}
    records = {row["requestId"]: row for row in load_adaptive_records(root)}
    fingerprint = str(manifest["executionFingerprint"])
    if any(row.get("executionFingerprint") != fingerprint for row in records.values()):
        raise ValueError("Adaptive request record execution fingerprint mismatch")
    learned = {key: dict(value) for key, value in (knowledge or {}).get("estimates", {}).items()}
    progressed = 0
    requests = plan["workload"]
    for item in requests:
        existing = records.get(item["requestId"])
        if existing and existing.get("state") in {"completed", "rejected"} and not force:
            if isinstance(existing.get("knowledgeAfter"), dict):
                learned = {key: dict(value) for key, value in existing["knowledgeAfter"].items()}
            progressed += 1
            continue
        candidate, reason = choose_candidate(plan, item, {"estimates": learned})
        record = {"schemaVersion": 1, "requestId": item["requestId"], "sequenceIndex": item["sequenceIndex"],
                  "executionFingerprint": fingerprint,
                  "state": "rejected" if candidate is None else "started", "taskId": item["taskId"],
                  "instanceId": item["instanceId"], "sizeBin": item["sizeBin"], "phase": item["phase"],
                  "selectedCandidate": candidate, "decision": reason, "toolDelayMs": item["toolDelayMs"]}
        directory = root / "adaptive-records"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{item['requestId']}.json"
        write_json(path, record)
        if candidate is None:
            records[item["requestId"]] = record
            progressed += 1
            continue
        trial_id = item["candidates"][candidate]
        trial = by_id[trial_id]
        attempt = _latest_attempt(attempts_for_trial(root, trial_id))
        if attempt and attempt["state"] == "started" and not retry_uncertain:
            raise ValueError(f"Adaptive request {item['requestId']} has an uncertain attempt; pass --retry-uncertain")
        if attempt and attempt["state"] in {"succeeded", "failed"} and not force:
            result = attempt["result"]
        else:
            decorator = lambda runtime, delay=item["toolDelayMs"]: DelayedToolRuntime(runtime, delay)
            _execute_durable([trial], artifact_root=root, manifest=manifest, force=force,
                             retry_uncertain=retry_uncertain, logger=logger, progress=False,
                             local_mcp_runtime_decorator=decorator)
            latest = _latest_attempt(attempts_for_trial(root, trial_id))
            result = latest["result"]
            attempt = latest
        record.update({"state": "completed", "trialId": trial_id,
                       "attemptId": attempt.get("attemptId"), "resultStatus": result.get("status"),
                       "timing": result.get("timing"), "metricsSummary": result.get("metricsSummary")})
        write_json(path, record)
        records[item["requestId"]] = record
        timing = result.get("timing", {}).get("durationMs")
        tokens = result.get("metricsSummary", {}).get("totalTokens")
        key = f"{candidate}|{item['sizeBin']}"
        prior = learned.get(key, {})
        for name, value in (("latencyMs", timing), ("totalTokens", tokens)):
            if isinstance(value, (int, float)):
                count_key = "latencyObservationCount" if name == "latencyMs" else "tokenObservationCount"
                count = prior.get(count_key, 0)
                prior[name] = (prior.get(name, 0) * count + value) / (count + 1)
                prior[count_key] = count + 1
        learned[key] = prior
        record["knowledgeAfter"] = {name: dict(value) for name, value in learned.items()}
        write_json(path, record)
        progressed += 1
    write_jsonl(root / "requests.jsonl", [records[key] for key in sorted(records)])
    print(f"Processed {progressed} adaptive request(s) → {root / 'requests.jsonl'}")
    return 0
