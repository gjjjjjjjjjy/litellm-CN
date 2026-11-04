from datetime import datetime, timezone
from typing import Annotated, Final, Literal, TypeAlias

from pydantic import AfterValidator, ConfigDict, Field, StringConstraints, model_validator
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
    prompt: str | None = None


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


ReviewScore: TypeAlias = Annotated[int, Field(ge=1, le=5)]


class QosVideoReviewInput(LiteLLMBaseModel):
    """One reviewer's ratings of a generated video, 1 (bad) to 5 (good); only the overall rating is required."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    overall: ReviewScore
    visual: ReviewScore | None = None
    detail: ReviewScore | None = None
    motion: ReviewScore | None = None
    alignment: ReviewScore | None = None
    physics: ReviewScore | None = None
    audio: ReviewScore | None = None
    comment: Annotated[str, Field(max_length=500)] | None = None


class QosVideoReview(QosVideoReviewInput):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reviewed_at: UtcDatetime


ReviewText: TypeAlias = Annotated[str, Field(max_length=500)]


class QosVideoAiReasons(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    visual: ReviewText = ""
    detail: ReviewText = ""
    motion: ReviewText = ""
    alignment: ReviewText = ""
    physics: ReviewText = ""


class QosVideoAiCheck(LiteLLMBaseModel):
    """One requirement the judge read out of the prompt, and whether the stills meet it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement: ReviewText
    met: bool
    evidence: ReviewText = ""


class QosVideoAiProblem(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    second: float = Field(ge=0)
    problem: ReviewText


class QosVideoAiScore(LiteLLMBaseModel):
    """A vision model's ratings of a video from one still per second, 1 (bad) to 5 (good); it hears no sound."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    judge: str = Field(min_length=1, max_length=200, description="The model that rated the stills")
    frames: int = Field(ge=1, description="How many stills, one per second, the judge saw")
    overall: ReviewScore
    visual: ReviewScore
    detail: ReviewScore
    motion: ReviewScore
    alignment: ReviewScore
    physics: ReviewScore
    reasons: QosVideoAiReasons
    checklist: tuple[QosVideoAiCheck, ...] = Field(default=(), max_length=30)
    problems: tuple[QosVideoAiProblem, ...] = Field(default=(), max_length=30)


class QosVideoAiReview(QosVideoAiScore):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reviewed_at: UtcDatetime


QosReviewVideoStatus: TypeAlias = Literal["generating", "completed", "failed"]


class QosReviewVideo(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    video_id: str
    model_group: str
    status: QosReviewVideoStatus
    created_at: UtcDatetime
    completed_at: UtcDatetime | None = Field(description="When the provider reported the video done; None until then")
    prompt: str = Field(description="The prompt the probe gave every model in its run")
    run: str | None = Field(description="The probe run that made the video; None for videos older than run ids")
    scheduled: bool = Field(description="Whether the run was one of the probe's daily scheduled runs")
    reviews: int
    overall: float | None = Field(description="Average overall rating of this video")
    my_review: QosVideoReview | None
    ai_review: QosVideoAiReview | None


class QosVideoReviewSummary(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_group: str
    videos: int
    reviews: int
    overall: float | None
    visual: float | None
    detail: float | None
    motion: float | None
    alignment: float | None
    physics: float | None
    audio: float | None


class QosVideoAiSummary(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_group: str
    videos: int
    overall: float
    visual: float
    detail: float
    motion: float
    alignment: float
    physics: float


class QosVideoReviewsResponse(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    start_time: UtcDatetime
    end_time: UtcDatetime
    summary: tuple[QosVideoReviewSummary, ...]
    ai_summary: tuple[QosVideoAiSummary, ...]
    videos: tuple[QosReviewVideo, ...]


PROBE_PROMPT_MAX_CHARS: Final = 500


class QosVideoEvaluationRequest(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=PROBE_PROMPT_MAX_CHARS)]


class QosVideoEvaluationStarted(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    prompt: str
    models: tuple[str, ...] = Field(description="The video models the probe is generating with")


class QosVideoEvaluationPrompt(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=PROBE_PROMPT_MAX_CHARS)]


class QosUsedPrompt(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    prompt: str
    last_used: UtcDatetime
    videos: int


class QosProbeModel(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_group: str
    image_to_video: bool
    last_price: float | None = Field(description="What the provider charged for this model's latest finished video")
    currency: str | None


class QosVideoEvaluationOptions(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool = Field(description="Whether the gateway knows a media probe to run evaluations on")
    models: tuple[QosProbeModel, ...]
    prompts: tuple[QosUsedPrompt, ...] = Field(description="Prompts earlier probe runs used, most recent first")


QosSpeechModality: TypeAlias = Literal["speech", "transcription"]


class QosSpeechReviewInput(LiteLLMBaseModel):
    """One reviewer's rating of a speech model's reading of the probe's sentence, 1 (bad) to 5 (good)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    overall: ReviewScore


class QosSpeechReview(QosSpeechReviewInput):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reviewed_at: UtcDatetime


class QosSpeechTranscript(LiteLLMBaseModel):
    """What a transcription model heard in the probe's recording, as the probe reports it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: Annotated[str, Field(max_length=2000)]


class QosSpeechResult(LiteLLMBaseModel):
    """One speech or transcription request of a probe run."""

    model_config = ConfigDict(frozen=True)

    request_id: str
    run: str
    scheduled: bool = Field(description="Whether the run was one of the probe's daily scheduled runs")
    model_group: str
    modality: QosSpeechModality
    created_at: UtcDatetime
    succeeded: bool
    error: str | None = Field(description="Why the request failed, as the gateway logged it")
    latency_ms: float
    audio_seconds: float | None = Field(description="Length of the audio read out or transcribed, when known")
    text: str = Field(description="The sentence the speech models read, which the recording also says")
    transcript: str | None = Field(description="What a transcription model heard; None until the probe reports it")
    reviews: int
    overall: float | None = Field(description="Average rating of this reading")
    my_review: QosSpeechReview | None


class QosSpeechEvaluationsResponse(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    start_time: UtcDatetime
    end_time: UtcDatetime
    results: tuple[QosSpeechResult, ...]


class QosSpeechProbeModel(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_group: str
    modality: QosSpeechModality


class QosSpeechEvaluationOptions(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool = Field(description="Whether the gateway knows a media probe to run evaluations on")
    models: tuple[QosSpeechProbeModel, ...]


class QosSpeechEvaluationStarted(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    models: tuple[str, ...] = Field(description="The speech and transcription models the probe is testing")


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
