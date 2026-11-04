"""
Speech evaluation: every probed speech model reads the same sentence and every probed transcription model transcribes
the same recording of it, on the probe's schedule or when the audio tab starts a run.

Results live on each request's own spend log row, like the probe's videos: the probe names its run and the sentence in
the request's spend log metadata, the gateway logs latency and audio length as usual, the probe reports what a
transcription model heard under `qos_speech_transcript`, and reviewers' ratings of a reading go under
`qos_speech_reviews` with one entry per reviewer. Speech audio stays in the probe's container, fetched through here.
"""

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import ConfigDict, TypeAdapter

from litellm.constants import LITELLM_PROXY_ADMIN_NAME
from litellm.proxy._types import CommonProxyErrors, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.management_endpoints.qos_access import require_admin, require_media_reviewer
from litellm.proxy.management_endpoints.qos_deployments import deployment_model_groups
from litellm.proxy.management_endpoints.qos_media import (
    QOS_MEDIA_KEY,
    SPEECH_CALL_TYPES,
    TRANSCRIPTION_CALL_TYPES,
)
from litellm.proxy.management_endpoints.qos_media_probe import (
    MediaProbe,
    ProbedDeployment,
    ask_probe,
    fetch_from_probe,
    first_of_each,
    listed_deployments,
    media_probe,
    probe_answer,
)
from litellm.proxy.management_endpoints.qos_media_summary import MEDIA_MODALITY, deployment_modalities
from litellm.proxy.management_endpoints.qos_sql import logged_model_group, sql_list
from litellm.proxy.management_endpoints.qos_summary import metrics_window, query_rows, utc_now
from litellm.proxy.management_endpoints.qos_video_reviews import PROBE_RUN, PROBE_SCHEDULED, RecordedReview
from litellm.types.llms.base import LiteLLMBaseModel
from litellm.types.qos import (
    QosSpeechEvaluationOptions,
    QosSpeechEvaluationsResponse,
    QosSpeechEvaluationStarted,
    QosSpeechModality,
    QosSpeechProbeModel,
    QosSpeechResult,
    QosSpeechReview,
    QosSpeechReviewInput,
    QosSpeechTranscript,
)

router: Final = APIRouter()

QOS_SPEECH_REVIEWS_KEY: Final = "qos_speech_reviews"
QOS_SPEECH_TRANSCRIPT_KEY: Final = "qos_speech_transcript"
SPEECH_RESULT_LIMIT: Final = 500
ERROR_LIMIT: Final = 300
START_TIMEOUT_SECONDS: Final = 30.0
AUDIO_TIMEOUT_SECONDS: Final = 30.0
_MODALITY_OF_MODE: Final[Mapping[str, QosSpeechModality]] = MappingProxyType(
    {"audio_speech": "speech", "audio_transcription": "transcription"}
)

SPEECH_RESULTS_SQL: Final = f"""
WITH probed AS (
    SELECT request_id, "startTime" AS created_at, {logged_model_group("$4")} AS model_group,
        {MEDIA_MODALITY} AS modality,
        {PROBE_RUN} AS run,
        {PROBE_SCHEDULED} AS scheduled,
        COALESCE(metadata -> 'spend_logs_metadata' ->> 'qos_probe_text', '') AS text,
        status IS DISTINCT FROM 'failure' AS succeeded,
        LEFT(metadata -> 'error_information' ->> 'error_message', {ERROR_LIMIT}) AS error,
        EXTRACT(epoch FROM ("endTime" - "startTime")) * 1000 AS latency_ms,
        (metadata -> '{QOS_MEDIA_KEY}' ->> 'audio_seconds')::float AS audio_seconds,
        metadata -> '{QOS_SPEECH_TRANSCRIPT_KEY}' ->> 'text' AS transcript,
        COALESCE(metadata -> '{QOS_SPEECH_REVIEWS_KEY}', '{{}}'::jsonb) AS reviews
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= $1::timestamp AND "startTime" < $2::timestamp AND {PROBE_RUN} IS NOT NULL
)
SELECT * FROM probed
WHERE modality IN ('speech', 'transcription')
ORDER BY created_at DESC
LIMIT {SPEECH_RESULT_LIMIT}
"""

RECORD_SPEECH_REVIEW_SQL: Final = f"""
UPDATE "LiteLLM_SpendLogs"
SET metadata = metadata || jsonb_build_object(
    '{QOS_SPEECH_REVIEWS_KEY}',
    COALESCE(metadata -> '{QOS_SPEECH_REVIEWS_KEY}', '{{}}'::jsonb) || jsonb_build_object($2::text, $3::jsonb)
)
WHERE request_id = $1 AND call_type IN ({sql_list(SPEECH_CALL_TYPES)}) AND {PROBE_RUN} IS NOT NULL
RETURNING request_id
"""

RECORD_TRANSCRIPT_SQL: Final = f"""
UPDATE "LiteLLM_SpendLogs"
SET metadata = metadata || jsonb_build_object('{QOS_SPEECH_TRANSCRIPT_KEY}', $2::jsonb)
WHERE request_id = $1 AND call_type IN ({sql_list(TRANSCRIPTION_CALL_TYPES)}) AND {PROBE_RUN} IS NOT NULL
RETURNING request_id
"""


class SpeechRow(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    created_at: datetime
    model_group: str
    modality: QosSpeechModality
    run: str
    scheduled: bool
    text: str
    succeeded: bool
    error: str | None
    latency_ms: float
    audio_seconds: float | None
    transcript: str | None
    reviews: Mapping[str, QosSpeechReview]


SPEECH_ROWS: Final = TypeAdapter(tuple[SpeechRow, ...])
RECORDED_ROWS: Final = TypeAdapter(tuple[RecordedReview, ...])


def speech_result(row: SpeechRow, reviewer: str) -> QosSpeechResult:
    overall: Final = tuple(review.overall for review in row.reviews.values())
    return QosSpeechResult(
        request_id=row.request_id,
        run=row.run,
        scheduled=row.scheduled,
        model_group=row.model_group,
        modality=row.modality,
        created_at=row.created_at,
        succeeded=row.succeeded,
        error=None if row.succeeded else row.error,
        latency_ms=row.latency_ms,
        audio_seconds=row.audio_seconds,
        text=row.text,
        transcript=row.transcript,
        reviews=len(overall),
        overall=sum(overall) / len(overall) if overall else None,
        my_review=row.reviews.get(reviewer),
    )


def speech_probe_models(deployments: tuple[ProbedDeployment, ...]) -> tuple[QosSpeechProbeModel, ...]:
    probed: Final = first_of_each(tuple(d for d in deployments if d.model_info.qos_probe is not None))
    return tuple(
        QosSpeechProbeModel(model_group=deployment.model_name, modality=modality)
        for deployment in probed
        if (modality := _MODALITY_OF_MODE.get(deployment.model_info.mode or "")) is not None
    )


def _reviewer(user_api_key_dict: UserAPIKeyAuth) -> str:
    return user_api_key_dict.user_id or LITELLM_PROXY_ADMIN_NAME


@router.get(
    "/qos/speech/evaluations",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosSpeechEvaluationsResponse,
)
async def get_qos_speech_evaluations(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    start_time: Annotated[datetime | None, Query(description="ISO 8601, defaults to 24 hours before end_time")] = None,
    end_time: Annotated[datetime | None, Query(description="ISO 8601, defaults to now")] = None,
    all_time: Annotated[
        bool, Query(description="Include all retained history; cannot be combined with start_time")
    ] = False,
) -> QosSpeechEvaluationsResponse:
    """Every speech and transcription request of the probe's runs in the window, newest first."""
    from litellm.proxy.proxy_server import llm_router, prisma_client

    require_media_reviewer(user_api_key_dict)
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    start, end = await metrics_window(prisma_client, start_time, end_time, all_time)
    rows: Final = SPEECH_ROWS.validate_python(
        await query_rows(
            prisma_client,
            SPEECH_RESULTS_SQL,
            start,
            end,
            deployment_modalities(llm_router),
            deployment_model_groups(llm_router),
        )
    )
    reviewer: Final = _reviewer(user_api_key_dict)
    return QosSpeechEvaluationsResponse(
        start_time=start, end_time=end, results=tuple(speech_result(row, reviewer) for row in rows)
    )


@router.put(
    "/qos/speech/review",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosSpeechReview,
)
async def put_qos_speech_review(
    request_id: Annotated[str, Query(min_length=1, description="The gateway's id of the speech request")],
    review: QosSpeechReviewInput,
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> QosSpeechReview:
    """Save the caller's rating of how a speech model read the sentence, replacing their earlier rating."""
    from litellm.proxy.proxy_server import prisma_client

    require_media_reviewer(user_api_key_dict)
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    saved: Final = QosSpeechReview.model_validate({**review.model_dump(), "reviewed_at": utc_now()})
    recorded: Final = RECORDED_ROWS.validate_python(
        await query_rows(
            prisma_client,
            RECORD_SPEECH_REVIEW_SQL,
            request_id,
            _reviewer(user_api_key_dict),
            saved.model_dump_json(),
        )
    )
    if not recorded:
        raise HTTPException(status_code=404, detail="No reading with this id was made by the probe")
    return saved


@router.put(
    "/qos/speech/evaluations/transcript",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosSpeechTranscript,
)
async def put_qos_speech_transcript(
    request_id: Annotated[str, Query(min_length=1, description="The gateway's id of the transcription request")],
    transcript: QosSpeechTranscript,
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> QosSpeechTranscript:
    """Keep what a transcription model heard in the probe's recording; 404 until the request has been logged."""
    from litellm.proxy.proxy_server import prisma_client

    require_admin(user_api_key_dict)
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    recorded: Final = RECORDED_ROWS.validate_python(
        await query_rows(prisma_client, RECORD_TRANSCRIPT_SQL, request_id, transcript.model_dump_json())
    )
    if not recorded:
        raise HTTPException(status_code=404, detail="No transcription with this id was logged for the probe yet")
    return transcript


@router.get(
    "/qos/speech/evaluations/options",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosSpeechEvaluationOptions,
)
async def get_qos_speech_evaluation_options(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    probe: Annotated[MediaProbe | None, Depends(media_probe)],
) -> QosSpeechEvaluationOptions:
    """The speech and transcription models a run would test."""
    require_media_reviewer(user_api_key_dict)
    return QosSpeechEvaluationOptions(available=probe is not None, models=speech_probe_models(listed_deployments()))


@router.post(
    "/qos/speech/evaluations",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosSpeechEvaluationStarted,
)
async def start_qos_speech_evaluation(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    probe: Annotated[MediaProbe | None, Depends(media_probe)],
) -> QosSpeechEvaluationStarted:
    """Have every probed speech model read the sentence and every transcription model transcribe its recording now."""
    require_admin(user_api_key_dict)
    content: Final = await ask_probe(probe, "/speech-evaluations", {}, START_TIMEOUT_SECONDS)
    return probe_answer(QosSpeechEvaluationStarted, content)


async def _probe_audio(probe: MediaProbe | None, path: str) -> Response:
    fetched: Final = await fetch_from_probe(probe, path, AUDIO_TIMEOUT_SECONDS)
    media_type: Final = fetched.headers["content-type"] if "content-type" in fetched.headers else None
    return Response(content=fetched.content, media_type=media_type or "application/octet-stream")


@router.get(
    "/qos/speech/audio",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_class=Response,
)
async def get_qos_speech_audio(
    request_id: Annotated[
        str, Query(pattern=r"^[A-Za-z0-9_-]{1,128}$", description="The gateway's id of the speech request")
    ],
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    probe: Annotated[MediaProbe | None, Depends(media_probe)],
) -> Response:
    """The audio a speech model returned in a probe run, as the probe kept it."""
    require_media_reviewer(user_api_key_dict)
    return await _probe_audio(probe, f"/audio/{request_id}")


@router.get(
    "/qos/speech/recording",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_class=Response,
)
async def get_qos_speech_recording(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    probe: Annotated[MediaProbe | None, Depends(media_probe)],
) -> Response:
    """The recording of the sentence that every transcription model gets."""
    require_media_reviewer(user_api_key_dict)
    return await _probe_audio(probe, "/recording")
