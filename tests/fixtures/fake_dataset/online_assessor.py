from __future__ import annotations

from ctxbench.adaptive.sensors import AssessmentInput, QualityObservation, SensorClass, SensorCost
from ctxbench.core.provenance import Provenance, TokenUsage
from ctxbench.dataset.capabilities import SignalCapability, SignalCost


class FakeQualityAssessor:
    """Deterministic, provider-free assessor used by adaptive workflow tests."""

    capability = SignalCapability(
        signal_id="fake-response-quality",
        version="1",
        metric_id="response_quality",
        sensor_class="semantic_proxy",
        value_provenance="derived",
        cost=SignalCost(None, "unavailable", 0, "derived"),
        value_scale="binary",
    )

    def assess(self, item: AssessmentInput) -> QualityObservation:
        value = float(bool(item.response.strip()))
        return QualityObservation(
            request_id=item.request_id,
            candidate_id=item.candidate_id,
            metric_id=self.capability.metric_id,
            value=value,
            value_scale=self.capability.value_scale or "unit",
            assessor_id=self.capability.signal_id,
            assessor_version=self.capability.version,
            sensor_class=SensorClass.SEMANTIC_PROXY,
            provenance=Provenance.DERIVED,
            cost=SensorCost(None, Provenance.UNAVAILABLE, TokenUsage(0, Provenance.DERIVED)),
        )


class FakeReferenceAssessor(FakeQualityAssessor):
    """Provider-free fixture for privileged-run propagation tests."""

    capability = SignalCapability(
        signal_id="fake-reference-quality",
        version="1",
        metric_id="response_quality",
        sensor_class="oracle",
        value_provenance="derived",
        cost=SignalCost(None, "unavailable", 0, "derived"),
        value_scale="binary",
        uses_reference_data=True,
        deployment_scope="reference-data",
    )

    def assess(self, item: AssessmentInput) -> QualityObservation:
        result = super().assess(item)
        return QualityObservation(
            request_id=result.request_id,
            candidate_id=result.candidate_id,
            metric_id=result.metric_id,
            value=result.value,
            value_scale=result.value_scale,
            assessor_id=self.capability.signal_id,
            assessor_version=self.capability.version,
            sensor_class=SensorClass.ORACLE,
            provenance=result.provenance,
            cost=result.cost,
            uses_reference_data=True,
        )


class FailingQualityAssessor(FakeQualityAssessor):
    def assess(self, item: AssessmentInput) -> QualityObservation:
        raise RuntimeError("synthetic assessor failure")
