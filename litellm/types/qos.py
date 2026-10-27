from datetime import datetime, timezone
from typing import Annotated, Final, Literal

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


PROVIDER_TASK_HIDDEN_PARAM: Final = "provider_task"


class QosProviderTask(LiteLLMBaseModel):
    """An asynchronous job as its provider reports it, such as a Moark video task, kept in hidden params."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    status: str
    created_at: UtcDatetime | None = None
    started_at: UtcDatetime | None = None
    completed_at: UtcDatetime | None = None
    price: float | None = None
    currency: str | None = None


class QosMedia(LiteLLMBaseModel):
    """What service quality needs from an audio or video request, stored on its spend log row as `qos_media`."""

    model_config = ConfigDict(frozen=True)

    input_chars: int | None = None
    audio_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    format: str | None = None
    task_id: str | None = None
    task_status: str | None = None
    queue_ms: float | None = None
    run_ms: float | None = None
    task_price: float | None = None
    task_currency: str | None = None


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
    vendor: str = Field(
        description="Who serves the model: the provider, or the endpoint host for OpenAI-compatible ones"
    )


class QosSummaryResponse(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    start_time: UtcDatetime
    end_time: UtcDatetime
    tag: str | None
    model_groups: tuple[QosModelGroupMetrics, ...]
    deployments: tuple[QosDeploymentMetrics, ...]


class QosAudioMetrics(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_group: str
    modality: Literal["speech", "transcription"]
    requests: int
    failed_requests: int
    audio_seconds: float = Field(description="Audio produced (speech) or transcribed (transcription) by served calls")
    input_chars: int = Field(description="Spoken characters sent to speech models, punctuation and spaces excluded")
    latency_ms: QosPercentiles = Field(description="End-to-end time of served calls")
    real_time_factor: QosPercentiles = Field(description="Latency over audio length; below 1 is faster than real time")


class QosVideoMetrics(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_group: str
    submitted: int
    failed_submissions: int
    succeeded: int
    failed: int
    cancelled: int
    queue_ms: QosPercentiles = Field(description="From the task being created to the provider starting it")
    run_ms: QosPercentiles = Field(description="From the provider starting a task to it succeeding")
    task_price: float | None = Field(description="Sum of the prices the provider reported for finished tasks")


class QosMediaResponse(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    start_time: UtcDatetime
    end_time: UtcDatetime
    audio: tuple[QosAudioMetrics, ...]
    video: tuple[QosVideoMetrics, ...]


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
    save_responses: bool = Field(default=False, description="Save this benchmark's question and response text")

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


class QosBenchmarkExchange(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    question: str
    answer: str | None
    reasoning: str | None
    error: str | None


class QosBenchmarkRequestLog(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    started_at: UtcDatetime
    concurrency: int | None
    model_id: str
    api_base: str
    vendor: str
    status: str | None
    response_check: Literal["passed", "crosstalk", "marker_missing"] | None
    exchange: QosBenchmarkExchange | None


class QosBenchmarkRequests(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    requests: tuple[QosBenchmarkRequestLog, ...]
    total: int
    page: int
    page_size: int


class QosTargetDeployment(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    provider: str
    vendor: str
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
    vendor: str
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


class QosOverall(LiteLLMBaseModel):
    """All model traffic in a window, for the dashboard's headline figures."""

    model_config = ConfigDict(frozen=True)

    requests: int
    failed_requests: int
    output_tokens: int
    output_tokens_per_second: float | None
    ttft_ms: QosPercentiles
    tpot_ms: QosPercentiles
    response_checks: QosResponseChecks


class QosTrendPoint(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    bucket_start: UtcDatetime
    requests: int
    failed_requests: int
    output_tokens: int
    ttft_ms: QosPercentiles
    tpot_ms: QosPercentiles


class QosTrendSeries(LiteLLMBaseModel):
    """One model, or one deployment of a model when grouped by deployment, over time."""

    model_config = ConfigDict(frozen=True)

    model_group: str
    model_id: str
    vendor: str
    api_base: str
    points: tuple[QosTrendPoint, ...]


class QosTrendsResponse(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    start_time: UtcDatetime
    end_time: UtcDatetime
    bucket_seconds: int
    group_by: Literal["model", "deployment"]
    current: QosOverall
    previous: QosOverall
    series: tuple[QosTrendSeries, ...]


class QosNewsItem(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    title: str
    link: str
    summary: str
    published_at: UtcDatetime | None


class QosNewsSource(LiteLLMBaseModel):
    """One configured feed and how its last fetch went."""

    model_config = ConfigDict(frozen=True)

    name: str
    url: str
    items: int
    error: str | None
    fetched_at: UtcDatetime


class QosNewsResponse(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[QosNewsItem, ...]
    sources: tuple[QosNewsSource, ...]


class QosAnnouncementCreate(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=2000)


class QosAnnouncement(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    body: str
    author: str
    created_at: UtcDatetime


class QosAnnouncementsResponse(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    announcements: tuple[QosAnnouncement, ...]


class QosNodeEvent(LiteLLMBaseModel):
    """A node whose health check changed between healthy and unhealthy."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["node_down", "node_recovered"]
    at: UtcDatetime
    model: str
    model_id: str
    vendor: str
    error: str | None


class QosBenchmarkEvent(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["benchmark"]
    at: UtcDatetime
    model: str
    run_id: str
    requests: int
    failed_requests: int
    crosstalk_responses: int


class QosModelAddedEvent(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["model_added"]
    at: UtcDatetime
    model: str
    created_by: str


QosActivityEvent = Annotated[QosNodeEvent | QosBenchmarkEvent | QosModelAddedEvent, Field(discriminator="kind")]


class QosActivityResponse(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    events: tuple[QosActivityEvent, ...]
