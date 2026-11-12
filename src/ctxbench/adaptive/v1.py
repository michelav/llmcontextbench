"""Minimal adaptive plan inputs for the v1 benchmark lifecycle."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from statistics import mean
from time import monotonic, sleep, time
from typing import Any

from ctxbench.benchmark.fingerprint import file_digest
from ctxbench.benchmark.models import TrialSpec
from ctxbench.benchmark.provisioning import validate_artifact_directory
from ctxbench.runtime.disturbances import RuntimeComponent, ToolRuntimeDisturbance
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
    if policy.get("type") in {"static", "cascade", "circuit_breaker"}:
        selected = _candidate(policy.get("candidate"))
        if selected not in configurations:
            raise ValueError("Policy candidate must be selected in the experiment candidates")
        fallbacks = policy.get("fallbacks", [])
        if not isinstance(fallbacks, list) or len(fallbacks) > 1:
            raise ValueError("Fallbacks must contain at most one candidate")
        for fallback in fallbacks:
            if _candidate(fallback) not in configurations or _candidate(fallback) == selected:
                raise ValueError("Fallback candidates must be distinct selected experiment candidates")
        if policy.get("type") == "circuit_breaker":
            window = policy.get("window", 3)
            minimum = policy.get("minimumObservations", 3)
            threshold = policy.get("failureRateThreshold", 0.5)
            if (type(window) is not int or window < 1 or type(minimum) is not int or not 1 <= minimum <= window
                    or type(threshold) not in (int, float) or not 0 < threshold <= 1):
                raise ValueError("Circuit breaker requires valid window, minimumObservations and failureRateThreshold")
    elif policy.get("type") == "threshold":
        if type(policy.get("latencyTargetMs")) not in (int, float) or policy["latencyTargetMs"] < 0:
            raise ValueError("Threshold policy requires a nonnegative latencyTargetMs")
        if "calibration" not in adaptation:
            raise ValueError("Threshold policy requires a separate static calibration run")
    elif policy.get("type") == "utility":
        if any(type(policy.get(key)) not in (int, float) or policy[key] < 0
               for key in ("latencyWeight", "tokenWeight")) or policy["latencyWeight"] + policy["tokenWeight"] <= 0:
            raise ValueError("Utility policy requires nonnegative latencyWeight and tokenWeight, not both zero")
        if "calibration" not in adaptation:
            raise ValueError("Utility policy requires a separate static calibration run")
    elif policy.get("type") == "budget":
        if type(policy.get("tokenBudget")) is not int or policy["tokenBudget"] < 0:
            raise ValueError("Budget policy requires a nonnegative integer tokenBudget")
        if "calibration" not in adaptation:
            raise ValueError("Budget policy requires a separate static calibration run")
    elif policy.get("type") == "explore":
        if type(policy.get("seed")) is not int or type(policy.get("explorationProbability")) not in (int, float) or not 0 <= policy["explorationProbability"] <= 1:
            raise ValueError("Explore policy requires an integer seed and explorationProbability in [0, 1]")
        if "calibration" not in adaptation:
            raise ValueError("Explore policy requires a separate static calibration run")
        if any(type(policy.get(key)) not in (int, float) or policy[key] < 0
               for key in ("latencyWeight", "tokenWeight")) or policy["latencyWeight"] + policy["tokenWeight"] <= 0:
            raise ValueError("Explore policy requires nonnegative utility weights, not both zero")
    else:
        raise ValueError("Unsupported adaptive policy type")

    phases = _validate_phases(adaptation.get("phases", []), len(workload))
    quota = adaptation.get("tokenQuota")
    if quota is not None and (not isinstance(quota, dict) or type(quota.get("tokens")) is not int
                              or quota["tokens"] < 1 or type(quota.get("windowSeconds")) is not int
                              or quota["windowSeconds"] < 1 or type(quota.get("bestEffort", False)) is not bool):
        raise ValueError("tokenQuota requires positive integer tokens/windowSeconds and optional bestEffort")
    if quota and not quota.get("bestEffort", False) and "calibration" not in adaptation:
        raise ValueError("Strict tokenQuota requires a separate static calibration run")
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
    if policy["type"] == "threshold" or policy["type"] in {"utility", "budget", "explore"} or (
            quota and not quota.get("bestEffort", False)):
        knowledge = _load_calibration(adaptation["calibration"], trials, planned, dataset)
    return {"schemaVersion": 1, "policy": dict(policy), "tokenQuota": quota,
            "candidateIds": configurations,
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
        failure_rate = phase.get("toolFailureRate", 0)
        failure_seed = phase.get("failureSeed")
        if (not isinstance(name, str) or not name or type(first) is not int or type(last) is not int
                or first != expected_start or last < first or last > workload_size
                or type(delay) is not int or delay < 0
                or type(failure_rate) not in (int, float) or not 0 <= failure_rate <= 1
                or (failure_rate > 0 and type(failure_seed) is not int)):
            raise ValueError("phases must cover contiguous workload ranges with valid delay/fault settings")
        result.append({"name": name, "firstRequest": first, "lastRequest": last,
                       "toolDelayMs": delay, "toolFailureRate": failure_rate,
                       "failureSeed": failure_seed})
        expected_start = last + 1
    if result and expected_start != workload_size + 1:
        raise ValueError("phases must cover the complete workload")
    return result


def choose_candidate(plan: dict, request: dict, knowledge: dict | None, *,
                     history: dict[str, list[dict]] | None = None,
                     spent_tokens: int = 0, unknown_spend: bool = False,
                     request_index: int = 1) -> tuple[str | None, str]:
    candidates = request["candidates"]
    policy = plan["policy"]
    if not candidates:
        return None, "no_eligible_candidate"
    if policy["type"] in {"static", "cascade"}:
        cid = _candidate(policy["candidate"])
        return (cid, "static") if cid in candidates else (None, "static_candidate_ineligible")
    if policy["type"] == "circuit_breaker":
        primary = _candidate(policy["candidate"])
        rows = (history or {}).get(primary, [])[-policy.get("window", 3):]
        failures = sum(row.get("status") != "success" for row in rows)
        open_now = len(rows) >= policy.get("minimumObservations", 3) and failures / len(rows) >= policy.get("failureRateThreshold", 0.5)
        if not open_now and primary in candidates:
            return primary, "circuit_closed"
        fallbacks = [_candidate(value) for value in policy.get("fallbacks", [])]
        chosen = next((cid for cid in fallbacks if cid in candidates), None)
        return chosen, "circuit_open" if chosen else "circuit_open_no_fallback"
    if policy["type"] == "budget":
        if unknown_spend and not policy.get("bestEffort", False):
            return None, "unknown_consumption"
        remaining = policy["tokenBudget"] - spent_tokens
        estimates = (knowledge or {}).get("estimates", {})
        costs = [(cid, estimates.get(f"{cid}|{request['sizeBin']}", {}).get("totalTokens")) for cid in candidates]
        feasible = [(cid, cost) for cid, cost in costs if isinstance(cost, (int, float)) and cost <= remaining]
        if feasible:
            return min(feasible, key=lambda row: (row[1], row[0]))[0], "budget_admitted"
        if policy.get("bestEffort"):
            known = [(cid, cost) for cid, cost in costs if isinstance(cost, (int, float))]
            chosen = min(known, key=lambda row: (row[1], row[0]))[0] if known else sorted(candidates)[0]
            return chosen, "budget_best_effort"
        return None, "budget_infeasible"
    if policy["type"] == "utility":
        estimates = (knowledge or {}).get("estimates", {})
        latency_weight = policy["latencyWeight"]
        token_weight = policy["tokenWeight"]
        ranked = []
        for cid in candidates:
            estimate = estimates.get(f"{cid}|{request['sizeBin']}", {})
            latency, tokens = estimate.get("latencyMs"), estimate.get("totalTokens")
            if ((latency_weight and not isinstance(latency, (int, float)))
                    or (token_weight and not isinstance(tokens, (int, float)))):
                continue
            score = latency_weight * (latency or 0) + token_weight * (tokens or 0)
            ranked.append((score, cid))
        return (min(ranked)[1], "minimum_weighted_cost") if ranked else (None, "unknown_utility_estimate")
    if policy["type"] == "explore":
        estimates = (knowledge or {}).get("estimates", {})
        baseline = min(candidates, key=lambda cid: _utility_rank(
            cid, request, estimates, policy["latencyWeight"], policy["tokenWeight"]))
        stream = sha256(f"{policy['seed']}:{request['requestId']}".encode()).digest()
        draw = int.from_bytes(stream[:8], "big") / (2**64)
        alternatives = sorted(cid for cid in candidates if cid != baseline)
        if alternatives and draw < policy["explorationProbability"]:
            offset = int.from_bytes(stream[8:16], "big") % len(alternatives)
            return alternatives[offset], "seeded_exploration"
        if _utility_rank(baseline, request, estimates, policy["latencyWeight"], policy["tokenWeight"])[0]:
            return None, "unknown_utility_estimate"
        return baseline, "utility_exploitation"
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


def _utility_rank(candidate: str, request: dict, estimates: dict,
                  latency_weight: float, token_weight: float) -> tuple[bool, float, str]:
    estimate = estimates.get(f"{candidate}|{request['sizeBin']}", {})
    tokens = estimate.get("totalTokens")
    latency = estimate.get("latencyMs")
    if ((latency_weight and not isinstance(latency, (int, float)))
            or (token_weight and not isinstance(tokens, (int, float)))):
        value = None
    else:
        value = latency_weight * (latency or 0) + token_weight * (tokens or 0)
    return value is None, float(value) if value is not None else float("inf"), candidate


class TokenQuota:
    """Restorable rolling token quota; rows are persisted observed usage with UTC timestamps."""

    def __init__(self, config: dict, records: list[dict], *, clock=time, sleeper=sleep,
                 monotonic_clock=monotonic):
        self.limit = config["tokens"]
        self.window = config["windowSeconds"]
        self.best_effort = config.get("bestEffort", False)
        self.clock, self.sleeper = clock, sleeper
        self.monotonic_clock = monotonic_clock
        self.rows = []
        self.unknown_usage = False
        for record in records:
            for attempt in record.get("attempts", []):
                timestamp, tokens = attempt.get("quotaTimestamp"), attempt.get("totalTokens")
                known_tokens = attempt.get("knownTotalTokens")
                if not isinstance(known_tokens, (int, float)) and isinstance(tokens, (int, float)):
                    known_tokens = tokens
                if timestamp and isinstance(known_tokens, (int, float)):
                    try:
                        parsed = datetime.fromisoformat(timestamp)
                        if parsed.tzinfo is None:
                            raise ValueError("timestamp must include a timezone")
                        self.rows.append((parsed.timestamp(), int(known_tokens)))
                        if not isinstance(tokens, (int, float)):
                            self.unknown_usage = True
                    except (TypeError, ValueError):
                        raise ValueError("Invalid persisted token quota timestamp")
                elif timestamp:
                    self.unknown_usage = True

    def wait_for_capacity(self, estimate: int | float | None) -> float | None:
        if self.unknown_usage and not self.best_effort:
            return None
        if estimate is None:
            return 0.0 if self.best_effort else None
        if estimate > self.limit and not self.best_effort:
            return None
        start = self.monotonic_clock()
        while True:
            now = self.clock()
            self.rows = [(stamp, tokens) for stamp, tokens in self.rows if now - stamp < self.window]
            if sum(tokens for _, tokens in self.rows) + estimate <= self.limit or self.best_effort:
                return (self.monotonic_clock() - start) * 1000
            oldest = min(stamp for stamp, _ in self.rows)
            self.sleeper(max(0.001, oldest + self.window - now))

    def record(self, timestamp: str, tokens: int | None, known_tokens: int | None = None) -> None:
        observed = known_tokens if isinstance(known_tokens, (int, float)) else tokens
        if observed is not None:
            self.rows.append((datetime.fromisoformat(timestamp).timestamp(), int(observed)))
        if tokens is None:
            self.unknown_usage = True


class DelayedToolRuntime:
    """Add an explicit per-call delay while preserving runtime ownership."""
    def __init__(self, inner, delay_ms: int, sleeper=sleep, *, failure_rate: float = 0, failure_seed: int = 0):
        self._delegate = ToolRuntimeDisturbance(
            inner, name="legacy-adaptive-tool-disturbance", component=RuntimeComponent.LOCAL_MCP,
            delay_ms=delay_ms, failure_rate=failure_rate, failure_seed=failure_seed, sleeper=sleeper,
        )

    def list_tools(self):
        return self._delegate.list_tools()

    def call_tool(self, name, arguments):
        return self._delegate.call_tool(name, arguments)

    def close(self):
        self._delegate.close()


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
    """Serially select, attempt, and record delivery outcomes per request."""
    from ctxbench.ai.engine import Engine
    from ctxbench.benchmark.executor import execute_runtime_request, resolve_trial_dataset
    from ctxbench.benchmark.results import serialize_run_result
    from ctxbench.benchmark.runtime_adapter import TrialRuntimeAdapter
    from ctxbench.execution.service import ExecutionRequest, ExecutionSession, TrialExecutionService
    from ctxbench.benchmark.execution_records import rebuild_responses
    from ctxbench.adaptive.sensors import MinimumResponseLengthSensor
    from ctxbench.runtime.models import ExecutionResult
    from ctxbench.ai.models.base import AIResult
    from ctxbench.util.clock import utc_now_iso

    by_id = {trial.trialId: trial for trial in runspecs}
    service = TrialExecutionService(root)
    records = {row["requestId"]: row for row in load_adaptive_records(root)}
    fingerprint = str(manifest["executionFingerprint"])
    if any(row.get("executionFingerprint") != fingerprint for row in records.values()):
        raise ValueError("Adaptive request record execution fingerprint mismatch")
    learned = {key: dict(value) for key, value in (knowledge or {}).get("estimates", {}).items()}
    quota = TokenQuota(plan["tokenQuota"], list(records.values())) if plan.get("tokenQuota") else None
    progressed = 0
    requests = plan["workload"]
    session = ExecutionSession(Engine(event_logger=_adaptive_event_logger(logger)))
    try:
        for item in requests:
            existing = records.get(item["requestId"])
            if existing and existing.get("state") in {"delivered", "failed", "rejected"} and not force:
                if isinstance(existing.get("knowledgeAfter"), dict):
                    learned = {key: dict(value) for key, value in existing["knowledgeAfter"].items()}
                progressed += 1
                continue
            history: defaultdict[str, list[dict]] = defaultdict(list)
            spent_tokens, unknown_spend = 0, False
            for previous in records.values():
                for previous_attempt in previous.get("attempts", []):
                    history[previous_attempt["candidate"]].append(previous_attempt)
                    tokens = previous_attempt.get("totalTokens")
                    known_tokens = previous_attempt.get("knownTotalTokens")
                    if not isinstance(known_tokens, (int, float)) and isinstance(tokens, (int, float)):
                        known_tokens = tokens
                    if isinstance(known_tokens, (int, float)):
                        spent_tokens += int(known_tokens)
                    if not isinstance(tokens, (int, float)):
                        unknown_spend = True
            candidate, reason = choose_candidate(plan, item, {"estimates": learned},
                                                 history=history, spent_tokens=spent_tokens,
                                                 unknown_spend=unknown_spend,
                                                 request_index=item["sequenceIndex"])
            policy = plan["policy"]
            if policy.get("type") == "cascade":
                configured_order = [_candidate(policy["candidate"])] + [
                    _candidate(value) for value in policy.get("fallbacks", [])]
                eligible_order = [cid for cid in configured_order if cid in item["candidates"]]
                candidate = eligible_order[0] if eligible_order else None
                reason = "cascade" if candidate else "no_eligible_candidate"
            phase_settings = next((row for row in plan.get("phases", []) if row["name"] == item["phase"]), {})
            record = {"schemaVersion": 1, "requestId": item["requestId"], "sequenceIndex": item["sequenceIndex"],
                      "executionFingerprint": fingerprint,
                      "state": "rejected" if candidate is None else "started", "taskId": item["taskId"],
                      "instanceId": item["instanceId"], "sizeBin": item["sizeBin"], "phase": item["phase"],
                      "selectedCandidate": candidate, "decision": reason, "toolDelayMs": item["toolDelayMs"],
                      "toolFailureRate": phase_settings.get("toolFailureRate", 0),
                      "failureSeed": phase_settings.get("failureSeed"),
                      "attempts": [], "delivery": None}
            selected_estimate = learned.get(f"{candidate}|{item['sizeBin']}", {}).get("totalTokens") if candidate else None
            record["selectionEstimate"] = {"totalTokens": selected_estimate,
                                            "provenance": "derived" if isinstance(selected_estimate, (int, float))
                                            else "unavailable"}
            directory = root / "adaptive-records"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{item['requestId']}.json"
            write_json(path, record)
            if candidate is None:
                records[item["requestId"]] = record
                progressed += 1
                continue
            order = ([cid for cid in configured_order if cid in item["candidates"]]
                     if policy.get("type") == "cascade" else [candidate])
            accepted = None
            request_started = monotonic()
            for cid in order:
                trial_id = item["candidates"].get(cid)
                if trial_id is None:
                    continue
                trial = by_id[trial_id]
                prior_attempts = service.attempts(trial_id)
                attempt = prior_attempts[-1] if prior_attempts else None
                if attempt and attempt["state"] == "started" and quota:
                    if not quota.best_effort:
                        raise ValueError("An uncertain attempt has unknown token usage; strict tokenQuota blocks recovery")
                    quota.unknown_usage = True
                quota_wait_ms = 0.0
                quota_estimate = None
                if quota:
                    quota_estimate = learned.get(f"{cid}|{item['sizeBin']}", {}).get("totalTokens")
                    quota_wait_ms = quota.wait_for_capacity(quota_estimate)
                    if quota_wait_ms is None:
                        record.setdefault("admissionRejections", []).append({"candidate": cid, "reason": "token_quota"})
                        write_json(path, record)
                        continue
                if attempt and attempt["state"] in {"succeeded", "failed"} and not force:
                    result = attempt["result"]
                    attempt_id = attempt["attemptId"]
                else:
                    decorator = lambda runtime, phase=phase_settings, seq=item["sequenceIndex"]: DelayedToolRuntime(
                        runtime, phase.get("toolDelayMs", item["toolDelayMs"]),
                        failure_rate=phase.get("toolFailureRate", 0),
                        failure_seed=(phase.get("failureSeed") or 0) + seq)

                    request = ExecutionRequest(
                        execution_id=trial_id,
                        workflow_id=str(manifest.get("experimentId", "adaptive")),
                        correlation_id=item["requestId"],
                        experiment_id=trial.experimentId,
                        execution_fingerprint=fingerprint,
                        task_id=trial.taskId,
                        instance_id=trial.instanceId,
                        candidate_id=cid,
                        payload=TrialRuntimeAdapter().to_runtime_request(trial),
                        trial_id=trial_id,
                    )
                    dataset = resolve_trial_dataset(trial)
                    runtime_adapter = TrialRuntimeAdapter()

                    def invoke(_request, active_session):
                        started_at = utc_now_iso()
                        started_clock = monotonic()
                        try:
                            runtime_result = execute_runtime_request(
                                _request.payload, active_session.resource, dataset,
                                local_mcp_runtime_decorator=decorator,
                            )
                            execution = runtime_adapter.to_trial_result(trial, runtime_result)
                        except Exception as exc:
                            execution = TrialRuntimeAdapter().to_trial_result(
                                trial,
                                ExecutionResult(
                                    ai_result=AIResult(answer="", error=str(exc)),
                                    started_at=started_at,
                                    finished_at=utc_now_iso(),
                                    duration_ms=max(0, int((monotonic() - started_clock) * 1000)),
                                ),
                            )
                        return serialize_run_result(
                            execution, artifact_root=root, write_trace=trial.trace.writeFiles,
                        )

                    outcome = service.execute(
                        request, session, invoke, force=force,
                        retry_uncertain=retry_uncertain,
                    )
                    result = outcome.result
                    attempt_id = outcome.attempt_id
                metrics = result.get("metricsSummary") or {}
                response = result.get("response")
                response_text = response if isinstance(response, str) else str(response or "")
                min_length = policy.get("minimumResponseLength", 0)
                sensor_observation = MinimumResponseLengthSensor(min_length).observe(
                    item["requestId"], cid, response_text,
                )
                sensor_accepted = sensor_observation.accepted
                sensor_duration = sensor_observation.cost.duration_ms
                success = result.get("status") == "success"
                row = {"candidate": cid, "trialId": trial_id, "attemptId": attempt_id,
                       "status": result.get("status"), "accepted": bool(success and sensor_accepted),
                       "durationMs": (result.get("timing") or {}).get("durationMs"),
                       "totalTokens": metrics.get("totalTokens"),
                       "knownTotalTokens": metrics.get("knownTotalTokens"),
                       "quotaWaitMs": quota_wait_ms,
                       "quotaEstimate": {"totalTokens": quota_estimate,
                                         "provenance": "derived" if isinstance(quota_estimate, (int, float))
                                         else "unavailable"} if quota else None,
                       "quotaTimestamp": datetime.now(timezone.utc).isoformat() if quota else None,
                           "sensor": {"type": sensor_observation.sensor_id,
                                      "sensorVersion": sensor_observation.sensor_version,
                                      "sensorClass": sensor_observation.sensor_class.value,
                                      "provenance": sensor_observation.provenance.value,
                                  "minimumResponseLength": min_length,
                                  "accepted": bool(success and sensor_accepted),
                                      "durationMs": sensor_duration,
                                      "durationProvenance": sensor_observation.cost.duration_provenance.value,
                                      "totalTokens": sensor_observation.cost.tokens.value,
                                      "totalTokensProvenance": sensor_observation.cost.tokens.provenance.value}}
                record["attempts"].append(row)
                if quota:
                    quota.record(row["quotaTimestamp"], row["totalTokens"], row["knownTotalTokens"])
                if success:
                    key = f"{cid}|{item['sizeBin']}"
                    prior = learned.get(key, {})
                    for name, value in (("latencyMs", row["durationMs"]), ("totalTokens", row["totalTokens"])):
                        if isinstance(value, (int, float)):
                            count_key = "latencyObservationCount" if name == "latencyMs" else "tokenObservationCount"
                            count = prior.get(count_key, 0)
                            prior[name] = (prior.get(name, 0) * count + value) / (count + 1)
                            prior[count_key] = count + 1
                    learned[key] = prior
                write_json(path, record)
                if row["accepted"]:
                    accepted = row
                    break
            durations = [row["durationMs"] for row in record["attempts"] if isinstance(row.get("durationMs"), (int, float))]
            known_tokens = [row.get("knownTotalTokens") if isinstance(row.get("knownTotalTokens"), (int, float))
                            else row.get("totalTokens") for row in record["attempts"]]
            known_tokens = [value for value in known_tokens if isinstance(value, (int, float))]
            all_tokens_known = all(isinstance(row.get("totalTokens"), (int, float)) for row in record["attempts"])
            rejected_for_quota = bool(record.get("admissionRejections")) and not record["attempts"]
            request_duration_ms = (monotonic() - request_started) * 1000
            record.update({"state": "rejected" if rejected_for_quota else "delivered" if accepted else "failed",
                           "delivery": ({"candidate": accepted["candidate"], "trialId": accepted["trialId"],
                                         "attemptId": accepted["attemptId"]} if accepted else None),
                           "durationMs": sum(durations) if len(durations) == len(record["attempts"]) else None,
                           "durationProvenance": "measured" if len(durations) == len(record["attempts"]) else "unavailable",
                           "knownTotalTokens": sum(known_tokens) if known_tokens else None,
                           "knownTotalTokensProvenance": "derived" if known_tokens else "unavailable",
                           "sensorDurationMs": sum(row["sensor"]["durationMs"] for row in record["attempts"]),
                           "sensorTotalTokens": sum(row["sensor"]["totalTokens"] for row in record["attempts"]),
                           "quotaWaitMs": sum(row["quotaWaitMs"] for row in record["attempts"]),
                           "requestDurationMs": request_duration_ms,
                           "requestDurationProvenance": "measured",
                           "totalTokens": sum(row["totalTokens"] for row in record["attempts"])
                               if all_tokens_known else None,
                           "totalTokensProvenance": "derived" if all_tokens_known else "unavailable",
                           "usageCompleteness": "complete" if all_tokens_known else "partial"})
            record["knowledgeAfter"] = {name: dict(value) for name, value in learned.items()}
            write_json(path, record)
            records[item["requestId"]] = record
            progressed += 1
        write_jsonl(root / "requests.jsonl", [records[key] for key in sorted(records)])
        rebuild_responses(root, execution_fingerprint=fingerprint)
    finally:
        session.close()
    print(f"Processed {progressed} adaptive request(s) → {root / 'requests.jsonl'}")
    return 0


def _adaptive_event_logger(logger):
    if logger is None:
        return None

    def emit(event_name: str, message: str, fields: dict[str, object]) -> None:
        payload = dict(fields)
        level = str(payload.pop("level", "INFO"))
        phase = str(payload.pop("phase", "EXECUTE"))
        logger.event(level, phase, event_name, message, **payload)

    return emit
