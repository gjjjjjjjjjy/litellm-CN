from datetime import datetime

from pydantic import ConfigDict

from litellm.types.llms.base import LiteLLMBaseModel


class QosPercentiles(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    p50: float | None
    p95: float | None
    p99: float | None


class QosModelGroupMetrics(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_group: str
    requests: int
    failed_requests: int
    streamed_requests: int
    output_tokens: int
    peak_concurrency: int
    first_request_at: datetime
    last_response_at: datetime
    requests_per_second: float
    output_tokens_per_second: float
    ttft_ms: QosPercentiles
    tpot_ms: QosPercentiles
    e2e_latency_ms: QosPercentiles


class QosDeploymentMetrics(QosModelGroupMetrics):
    model_id: str
    model: str
    api_base: str


class QosSummaryResponse(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    start_time: datetime
    end_time: datetime
    tag: str | None
    model_groups: tuple[QosModelGroupMetrics, ...]
    deployments: tuple[QosDeploymentMetrics, ...]
