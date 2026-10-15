"""Deterministic V3 policy state; decisions depend only on frozen estimates and prior execution."""
import random
from collections import defaultdict


class Controller:
    def __init__(self, plan, episode):
        self.plan, self.episode = plan, episode
        self.policy = episode['policy']
        self.order = plan['configurations']
        self.observed = defaultdict(list)
        self.current = None
        self.current_by = {}
        self.last_switch_by = {}
        self.probes = 0
        self.consumed = 0
        self.estimated = 0
        self.unknown = False
        self.excluded_until = {}
        self.window_start = {}
        self.avoided = {}
        self.attempted = defaultdict(list)
        self.flagged_sources = set()
        self.source_of = {item['instanceId']: item.get('repo') for item in plan.get('index', [])}
        self.index = 0
        self.stopped = False
        if self.policy['type'] == 'random-eligible':
            self.rng = random.Random(f"{self.policy['seed']}:{episode['seed']}:{episode['repeat']}")

    def _calibration(self, cid, size, metric):
        return self.plan['estimates'][cid][size]['latencyMs' if metric == 'durationMs' else 'tokens']

    def _fresh(self, rows):
        ttl = self.policy.get('estimateTtlRequests')
        if not ttl:
            return rows
        # Expired observations fall away, so an avoided configuration reverts to calibration.
        return [o for o in rows if o['sequenceIndex'] > self.index+1-ttl]

    def _estimate(self, cid, size, metric):
        if self.policy['type'] == 'router' and self.policy['adaptive']:
            window = self.policy['updateWindow']
            minimum = self.policy.get('minimumObservations', 3)
            if self.policy.get('estimator', 'per-bin-mean') == 'pooled-ratio':
                ratio = self._ratio(cid, metric, window, minimum)
                base = self._calibration(cid, size, metric)
                if ratio is not None and base is not None:
                    return base*ratio
            else:
                sample = self._fresh(self.observed[(cid, size)])
                values = [o[metric] for o in sample[-window:] if o['status'] == 'success' and o[metric] is not None]
                if len(values) >= minimum:
                    return sum(values)/len(values)
        return self._calibration(cid, size, metric)

    def _ratio(self, cid, metric, window, minimum):
        """Observed/calibrated ratio pooled across size bins for one configuration."""
        ratios = []
        for o in self._fresh(self.observed[(cid, 'all')]):
            base = self._calibration(cid, o['sizeBin'], metric)
            if o['status'] == 'success' and o[metric] is not None and base:
                ratios.append(o[metric]/base)
        ratios = ratios[-window:]
        return sum(ratios)/len(ratios) if len(ratios) >= minimum else None

    def _routing_latency(self, cid, size):
        """Mean latency, or the calibration quantile scaled by current/calibrated mean."""
        estimate = self._estimate(cid, size, 'durationMs')
        quantile = self.policy.get('latencyQuantile')
        if quantile is None or estimate is None:
            return estimate
        calibrated = self._calibration(cid, size, 'durationMs')
        tail = self.plan['latencyQuantiles'][cid][size].get(str(quantile))
        if tail is None or not calibrated:
            return estimate
        return tail*estimate/calibrated

    def _value(self, cid, size, criterion):
        return self._routing_latency(cid, size) if criterion == 'durationMs' else self._estimate(cid, size, 'tokens')

    def _rank(self, candidates, size):
        limit = self.plan['definition'].get('latencyLimitMs')
        latency = {cid: self._routing_latency(cid, size) for cid in candidates}
        tokens = {cid: self._estimate(cid, size, 'tokens') for cid in candidates}
        within = [cid for cid in candidates if limit is not None and latency[cid] is not None and latency[cid] <= limit]
        if within:
            return min(within, key=lambda cid: (tokens[cid] is None, tokens[cid] if tokens[cid] is not None else float('inf'), self.order.index(cid)))
        return min(candidates, key=lambda cid: (latency[cid] is None, latency[cid] if latency[cid] is not None else float('inf'), self.order.index(cid)))

    def _eligible(self, instance):
        result = []
        for cid in self.order:
            candidate = self.plan['requests'][instance]['candidates'][cid]
            fit = candidate['context_fit']
            if candidate['executable'] and fit['input_tokens'] + fit['output_reservation'] <= fit['context_limit']:
                result.append(cid)
        return result

    def _probe(self, index, chosen, eligible):
        if self.policy.get('probeMode', 'round-robin') == 'targeted':
            spacing = self.policy['avoidedProbeInterval']
            due = [cid for cid, last in self.avoided.items()
                   if cid in eligible and cid != chosen and index+1-last >= spacing]
            if due:
                probe = min(due, key=lambda cid: (self.avoided[cid], self.order.index(cid)))
                self.avoided[probe] = index+1
                self.probes += 1
                return probe, True
        interval = self.policy.get('probeInterval')
        if not interval or (index+1) % interval:
            return chosen, False
        alternatives = [cid for cid in eligible if cid != chosen]
        if not alternatives:
            return chosen, False
        probe = alternatives[self.probes % len(alternatives)]
        self.probes += 1
        return probe, True

    def _forecast(self, cid, start):
        if self.policy.get('forecast', 'lookahead') == 'expected':
            # Request count is known; future request features are not read.
            per_request = 0.0
            for size, share in self.plan['calibrationSizeMix'].items():
                value = self._estimate(cid, size, 'tokens')
                if value is None:
                    return None
                per_request += share*value
            return (len(self.episode['workload'])-start)*per_request
        values = []
        for instance in self.episode['workload'][start:]:
            candidate = self.plan['requests'][instance]['candidates'][cid]
            fit = candidate['context_fit']
            if not candidate['executable'] or fit['input_tokens']+fit['output_reservation'] > fit['context_limit']:
                return None
            size = self.plan['requests'][instance]['sizeBin']
            value = self._estimate(cid, size, 'tokens')
            if value is None:
                return None
            values.append(value)
        return sum(values)

    def _quality_eligible(self, cid):
        floor = self.plan['definition'].get('minimumCalibrationPassRate')
        if floor is None:
            return True
        rate = self.plan['quality'][cid]['passRate']
        return rate is not None and rate >= floor

    def _budget(self, index, eligible):
        remaining = self.plan['definition']['tokenBudget'] - self.consumed - self.estimated
        if (self.unknown and self.policy.get('unknownUsage', 'stop') == 'stop') or self.stopped:
            return None, 'unknown_consumption' if self.unknown else 'budget_infeasible', False
        eligible = [cid for cid in eligible if self._quality_eligible(cid)]
        if self.policy.get('mode', 'incumbent') == 'pace':
            return self._pace(index, eligible, remaining)
        feasible = [(cid, self._forecast(cid, index)) for cid in eligible]
        feasible = [(cid, demand) for cid, demand in feasible if demand is not None and demand <= remaining]
        if not feasible:
            self.stopped = True
            return None, 'budget_infeasible', False
        if self.current in dict(feasible):
            chosen = self.current
            reason = 'incumbent_affordable'
        else:
            chosen = min(feasible, key=lambda row: (row[1], self.order.index(row[0])))[0]
            self.current = chosen
            reason = 'lowest_feasible_tokens'
        # A probe can change only this request; its projected total must still fit.
        interval = self.policy['probeInterval']
        if (index+1) % interval == 0:
            alternatives = [cid for cid, _ in feasible if cid != chosen]
            if alternatives:
                probe = alternatives[self.probes % len(alternatives)]
                size = self.plan['requests'][self.episode['workload'][index]]['sizeBin']
                new = self._estimate(probe, size, 'tokens')
                old = self._estimate(chosen, size, 'tokens')
                demand = self._forecast(chosen, index)
                if new is not None and old is not None and demand is not None and self.consumed+self.estimated+demand-old+new <= self.plan['definition']['tokenBudget']:
                    self.probes += 1
                    return probe, 'scheduled_probe', True
        return chosen, reason, False

    def _pace(self, index, eligible, remaining):
        """Fastest qualified configuration whose cost still leaves the cheapest plan for the rest."""
        size = self.plan['requests'][self.episode['workload'][index]]['sizeBin']
        rest = [self._forecast(cid, index+1) for cid in self.order if self._quality_eligible(cid)]
        rest = min((value for value in rest if value is not None), default=None)
        if rest is None:
            self.stopped = True
            return None, 'budget_infeasible', False
        ranked = sorted(eligible, key=lambda cid: (self._estimate(cid, size, 'durationMs') is None,
                                                   self._estimate(cid, size, 'durationMs') or 0, self.order.index(cid)))
        for cid in ranked:
            cost = self._estimate(cid, size, 'tokens')
            if cost is not None and cost + rest <= remaining:
                return cid, 'paced', False
        self.stopped = True
        return None, 'budget_infeasible', False

    def _schedule(self, index, size, eligible):
        mapping = self.policy['default']
        for phase in self.policy['phases']:
            if phase['firstRequest'] <= index+1 <= phase['lastRequest']:
                mapping = phase['configurationBySize']
        chosen = mapping.get(size)
        if chosen in eligible:
            return chosen, 'schedule', False
        return (eligible[0], 'schedule_fallback', False) if eligible else (None, 'no_eligible_candidate', False)

    def _reliability(self, index, eligible):
        monitored = set(self.policy['failureClasses'])
        window = self.policy['window']
        minimum = self.policy['minimumObservations']
        threshold = self.policy['failureRateThreshold']
        candidates = []
        recovery = []
        for cid in eligible:
            history = self.observed[(cid, 'all')][self.window_start.get(cid, 0):][-window:]
            if cid in self.excluded_until:
                if index+1 >= self.excluded_until[cid]:
                    recovery.append(cid)
                continue
            if len(history) >= minimum and sum(bool(monitored.intersection(o['failures'])) for o in history)/len(history) >= threshold:
                self.excluded_until[cid] = index+1+self.policy['cooldownRequests']
                continue
            candidates.append(cid)
        if recovery:
            chosen = recovery[self.probes % len(recovery)]
            self.probes += 1
            return chosen, 'recovery_probe', True
        if not candidates:
            return None, 'all_candidates_ineligible', False
        size = self.plan['requests'][self.episode['workload'][index]]['sizeBin']
        return self._router_decision(index, candidates, size)

    def _router_decision(self, index, eligible, size):
        # Global scope reproduces v1; bin scope keeps hysteresis within one size bin.
        scope = size if self.policy.get('incumbentScope', 'global') == 'bin' else None
        current = self.current_by.get(scope)
        best = self._rank(eligible, size)
        chosen = best
        if current in eligible and best != current:
            cooldown = index+1-self.last_switch_by.get(scope, 0) <= self.policy.get('cooldownRequests', 5)
            limit = self.plan['definition'].get('latencyLimitMs', float('inf'))
            best_latency, current_latency = self._routing_latency(best, size), self._routing_latency(current, size)
            best_meets = best_latency is not None and best_latency <= limit
            criterion = 'tokens' if best_meets else 'durationMs'
            old = self._value(current, size, criterion)
            new = self._value(best, size, criterion)
            material = new is not None and (old is None or new <= old*(1-self.policy.get('materialImprovement', .10)))
            if (self.policy.get('switchOnObjectiveMiss') and best_meets
                    and current_latency is not None and current_latency > limit):
                # The documented contract: meeting the objective outranks token cost.
                material = True
            if cooldown or not material:
                chosen = current
        if chosen != current:
            self.current_by[scope] = chosen
            self.last_switch_by[scope] = index+1
            self.avoided.pop(chosen, None)
            if current is not None and current not in self.current_by.values():
                self.avoided[current] = index+1
        actual, probe = self._probe(index, chosen, eligible)
        return actual, 'scheduled_probe' if probe else 'router', probe

    def _cascade(self, instance, eligible):
        fallbacks = [cid for cid in self.policy['fallbacks'] if cid in eligible]
        if (self.policy.get('memory') == 'source' and fallbacks
                and self.source_of.get(instance) in self.flagged_sources):
            return fallbacks[0], 'source_memory', False
        if self.policy['primary'] in eligible:
            return self.policy['primary'], 'primary', False
        if fallbacks:
            return fallbacks[0], 'primary_ineligible', False
        return None, 'no_eligible_candidate', False

    def decide_fallback(self, index, observation):
        """Within-request fallback after an observed trigger failure; never reads evaluation."""
        if self.policy['type'] != 'cascade' or observation is None or observation['status'] == 'success':
            return None
        triggers = set(self.policy.get('triggerFailureClasses', ['step-limit', 'tool-use']))
        if not triggers.intersection(observation['failures']):
            return None
        instance = self.episode['workload'][index]
        if observation['configuration'] == self.policy['primary']:
            self.flagged_sources.add(self.source_of.get(instance))
        eligible = self._eligible(instance)
        used = self.attempted[index]
        for cid in self.policy['fallbacks']:
            if cid in eligible and cid not in used:
                return {'configuration': cid, 'reason': 'fallback', 'probe': False}
        return None

    def decide(self, index):
        self.index = index
        instance = self.episode['workload'][index]
        eligible = self._eligible(instance)
        size = self.plan['requests'][instance]['sizeBin']
        kind = self.policy['type']
        if not eligible:
            chosen, reason, probe = None, 'no_eligible_candidate', False
        elif kind == 'fixed':
            chosen = self.policy['configuration'] if self.policy['configuration'] in eligible else None
            reason, probe = ('fixed' if chosen else 'context_capacity'), False
        elif kind == 'budget':
            chosen, reason, probe = self._budget(index, eligible)
        elif kind == 'reliability':
            chosen, reason, probe = self._reliability(index, eligible)
        elif kind == 'cascade':
            chosen, reason, probe = self._cascade(instance, eligible)
        elif kind == 'schedule':
            chosen, reason, probe = self._schedule(index, size, eligible)
        elif kind == 'random-eligible':
            chosen, reason, probe = self.rng.choice(eligible), 'random', False
        else:
            chosen, reason, probe = self._router_decision(index, eligible, size)
        return {'configuration': chosen, 'reason': reason, 'probe': probe}

    def observe(self, observation):
        if observation is None:
            return
        cid = observation['configuration']
        size = observation['sizeBin']
        token = observation['tokens']
        row = {'status': observation['status'], 'durationMs': observation['durationMs'],
               'tokens': token['value'], 'failures': observation['failures'],
               'sizeBin': size, 'sequenceIndex': observation['sequenceIndex']}
        self.attempted[observation['sequenceIndex']-1].append(cid)
        self.observed[(cid,size)].append(row)
        self.observed[(cid,'all')].append(row)
        if token['value'] is None:
            self.unknown = True
            partial = token.get('knownPartial') or 0
            self.consumed += partial
            if self.policy.get('unknownUsage') == 'bounded':
                bound = self.plan['tokenQuantiles'][cid][size]['p95']
                self.estimated += max(0, (bound or 0)-partial)
        else:
            self.consumed += token['value']
        if self.policy['type'] == 'reliability' and cid in self.excluded_until:
            monitored = set(self.policy['failureClasses'])
            if not monitored.intersection(observation['failures']):
                self.excluded_until.pop(cid)
                if self.policy.get('resetOnRecovery'):
                    # Close the circuit: judge the configuration only from the clean probe onward.
                    self.window_start[cid] = len(self.observed[(cid, 'all')])-1
            else:
                self.excluded_until[cid] = observation['sequenceIndex']+self.policy['cooldownRequests']

    def ledger(self):
        budget = self.plan['definition'].get('tokenBudget')
        ledger = {'knownTokens': self.consumed, 'unknownConsumption': self.unknown,
                  'budget': budget, 'overshoot': max(0, self.consumed-budget) if budget is not None else None}
        if self.policy.get('unknownUsage') == 'bounded':
            ledger['estimatedTokens'] = self.estimated
            ledger['estimatedTokensProvenance'] = 'estimated'
            ledger['estimatedOvershoot'] = max(0, self.consumed+self.estimated-budget)
        return ledger
