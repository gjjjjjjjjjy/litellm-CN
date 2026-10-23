from datetime import datetime, timezone
from typing import Annotated, Final

from pydantic import AfterValidator, ConfigDict, Field, model_validator
from typing_extensions import Self

from litellm.types.llms.base import LiteLLMBaseModel


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


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
    first_request_at: UtcDatetime
    last_response_at: UtcDatetime
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

    start_time: UtcDatetime
    end_time: UtcDatetime
    tag: str | None
    model_groups: tuple[QosModelGroupMetrics, ...]
    deployments: tuple[QosDeploymentMetrics, ...]


QOS_BENCHMARK_MAX_REQUESTS: Final = 5000


class QosBenchmarkRequest(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_group: str = Field(min_length=1)
    concurrency: tuple[Annotated[int, Field(ge=1, le=256)], ...] = Field(min_length=1, max_length=8)
    requests_per_worker: int = Field(ge=1, le=50)
    max_tokens: int = Field(ge=1, le=8192)

    @property
    def total_requests(self) -> int:
        return sum(self.concurrency) * self.requests_per_worker

    @model_validator(mode="after")
    def _bounded_total(self) -> Self:
        if self.total_requests > QOS_BENCHMARK_MAX_REQUESTS:
            raise ValueError(f"A benchmark may send at most {QOS_BENCHMARK_MAX_REQUESTS} requests")
        return self


class QosBenchmarkStarted(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    model_group: str
    concurrency: tuple[int, ...]
    requests_per_worker: int
    max_tokens: int
    total_requests: int
    started_at: UtcDatetime


class QosBenchmarkRun(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    model_group: str
    requests: int
    failed_requests: int
    started_at: UtcDatetime
    last_response_at: UtcDatetime


class QosBenchmarkListResponse(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    runs: tuple[QosBenchmarkRun, ...]


class QosBenchmarkLevel(QosModelGroupMetrics):
    concurrency: int


class QosBenchmarkDetail(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    levels: tuple[QosBenchmarkLevel, ...]
    deployments: tuple[QosDeploymentMetrics, ...]
