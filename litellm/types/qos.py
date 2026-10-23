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


class QosResponseChecks(LiteLLMBaseModel):
    """How many benchmark responses were checked for cross-talk with concurrent requests, and what was found."""

    model_config = ConfigDict(frozen=True)

    checked: int
    crosstalk: int
    marker_missing: int


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
    response_checks: QosResponseChecks


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
    deployment_ids: tuple[Annotated[str, Field(min_length=1)], ...] = Field(
        default=(),
        max_length=8,
        description="Deployments of model_group to test one after another; empty load-balances across all of them",
    )
    concurrency: tuple[Annotated[int, Field(ge=1, le=256)], ...] = Field(min_length=1, max_length=8)
    requests_per_worker: int = Field(ge=1, le=50)
    max_tokens: int = Field(ge=1, le=8192)

    @property
    def targets(self) -> tuple[str, ...]:
        return self.deployment_ids if self.deployment_ids else (self.model_group,)

    @property
    def total_requests(self) -> int:
        return sum(self.concurrency) * self.requests_per_worker * len(self.targets)

    @model_validator(mode="after")
    def _valid_plan(self) -> Self:
        if len(set(self.deployment_ids)) != len(self.deployment_ids):
            raise ValueError("Each deployment may be tested only once per benchmark")
        if self.total_requests > QOS_BENCHMARK_MAX_REQUESTS:
            raise ValueError(f"A benchmark may send at most {QOS_BENCHMARK_MAX_REQUESTS} requests")
        return self


class QosBenchmarkStarted(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    model_group: str
    deployment_ids: tuple[str, ...]
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
    crosstalk_responses: int
    started_at: UtcDatetime
    last_response_at: UtcDatetime


class QosBenchmarkListResponse(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    runs: tuple[QosBenchmarkRun, ...]


class QosInterference(LiteLLMBaseModel):
    """Requests outside the benchmark that the gateway sent to the same node while a level was running."""

    model_config = ConfigDict(frozen=True)

    same_deployment: int
    same_endpoint: int


class QosBenchmarkLevel(QosModelGroupMetrics):
    concurrency: int
    interference: QosInterference


class QosBenchmarkDeploymentLevel(QosDeploymentMetrics):
    concurrency: int
    interference: QosInterference


class QosBenchmarkDetail(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    levels: tuple[QosBenchmarkLevel, ...]
    deployments: tuple[QosDeploymentMetrics, ...]
    deployment_levels: tuple[QosBenchmarkDeploymentLevel, ...]


class QosTargetDeployment(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    provider: str
    api_base: str
    upstream_model: str


class QosTargetModel(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_group: str
    deployments: tuple[QosTargetDeployment, ...]


class QosTargetsResponse(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    models: tuple[QosTargetModel, ...]


class QosHealthNode(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_name: str
    model_id: str
    api_base: str
    upstream_model: str
    checks: int
    failures: int
    availability: float
    latest_status: str
    last_error: str | None
    last_failure_at: UtcDatetime | None
    last_checked_at: UtcDatetime


class QosHealthProbe(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    api_base: str
    probes: int
    latency_ms: QosPercentiles
    last_probe_at: UtcDatetime


class QosHealthResponse(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    start_time: UtcDatetime
    end_time: UtcDatetime
    nodes: tuple[QosHealthNode, ...]
    probes: tuple[QosHealthProbe, ...]


class QosBenchmarkDeleted(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    deleted_requests: int
