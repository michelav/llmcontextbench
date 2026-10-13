"""Deterministic V3 policy state; decisions depend only on frozen estimates and prior execution."""
from collections import defaultdict


class Controller:
    def __init__(self, plan, episode):
        self.plan, self.episode = plan, episode
        self.policy = episode['policy']
        self.order = plan['configurations']
        self.observed = defaultdict(list)
        self.current = None
        self.last_switch = 0
        self.probes = 0
        self.consumed = 0
        self.unknown = False
        self.excluded_until = {}
        self.stopped = False

    def _estimate(self, cid, size, metric):
        sample = self.observed[(cid, size)]
        if self.policy['type'] == 'router' and self.policy['adaptive']:
            values = [o[metric] for o in sample[-self.policy['updateWindow']:] if o['status'] == 'success' and o[metric] is not None]
            if len(values) >= 3:
                return sum(values)/len(values)
        return self.plan['estimates'][cid][size]['latencyMs' if metric == 'durationMs' else 'tokens']

    def _rank(self, candidates, size):
        limit = self.plan['definition'].get('latencyLimitMs')
        latency = {cid: self._estimate(cid, size, 'durationMs') for cid in candidates}
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
        remaining = self.plan['definition']['tokenBudget'] - self.consumed
        if self.unknown or self.stopped:
            return None, 'unknown_consumption' if self.unknown else 'budget_infeasible', False
        eligible = [cid for cid in eligible if self._quality_eligible(cid)]
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
                if new is not None and old is not None and demand is not None and self.consumed+demand-old+new <= self.plan['definition']['tokenBudget']:
                    self.probes += 1
                    return probe, 'scheduled_probe', True
        return chosen, reason, False

    def _reliability(self, index, eligible):
        monitored = set(self.policy['failureClasses'])
        window = self.policy['window']
        minimum = self.policy['minimumObservations']
        threshold = self.policy['failureRateThreshold']
        candidates = []
        recovery = []
        for cid in eligible:
            history = self.observed[(cid, 'all')][-window:]
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
        best = self._rank(candidates, size)
        return self._router_decision(index, candidates, size)

    def _router_decision(self, index, eligible, size):
        best = self._rank(eligible, size)
        chosen = best
        if self.current in eligible and best != self.current:
            cooldown = index+1-self.last_switch <= self.policy.get('cooldownRequests', 5)
            criterion = 'tokens' if self._estimate(best, size, 'durationMs') is not None and self._estimate(best, size, 'durationMs') <= self.plan['definition'].get('latencyLimitMs',float('inf')) else 'durationMs'
            old = self._estimate(self.current, size, criterion)
            new = self._estimate(best, size, criterion)
            material = new is not None and (old is None or new <= old*(1-self.policy.get('materialImprovement', .10)))
            if cooldown or not material:
                chosen = self.current
        if chosen != self.current:
            self.current = chosen
            self.last_switch = index+1
        actual, probe = self._probe(index, chosen, eligible)
        return actual, 'scheduled_probe' if probe else 'router', probe

    def decide(self, index):
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
               'tokens': token['value'], 'failures': observation['failures']}
        self.observed[(cid,size)].append(row)
        self.observed[(cid,'all')].append(row)
        if token['value'] is None:
            self.unknown = True
            self.consumed += token.get('knownPartial') or 0
        else:
            self.consumed += token['value']
        if self.policy['type'] == 'reliability' and cid in self.excluded_until:
            monitored = set(self.policy['failureClasses'])
            if not monitored.intersection(observation['failures']):
                self.excluded_until.pop(cid)
            else:
                self.excluded_until[cid] = observation['sequenceIndex']+self.policy['cooldownRequests']

    def ledger(self):
        budget = self.plan['definition'].get('tokenBudget')
        return {'knownTokens': self.consumed, 'unknownConsumption': self.unknown,
                'budget': budget, 'overshoot': max(0, self.consumed-budget) if budget is not None else None}
