"""
Video review: the videos the probe made, to watch and rate by hand, with a vision model's ratings beside them.

Only videos the probe made are reviewed, on its schedule or from the review tab: every model in a run got the same
prompt, so their ratings compare, and theirs is the only prompt the gateway stores. The probe names its run in each
request's spend log metadata (`qos_probe_run`), so a run's videos are shown together. Ratings live on the video's
creation spend log row, by hand under `qos_video_reviews` with one entry per reviewer and the vision model's under
`qos_video_ai_review`, so they age out with the rest of service quality data and need no table of their own.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Final

from pydantic import ConfigDict, TypeAdapter

from litellm.proxy.management_endpoints.qos_media import (
    QOS_MEDIA_KEY,
    VIDEO_CREATE_CALL_TYPES,
    VIDEO_STATUS_CALL_TYPES,
)
from litellm.proxy.management_endpoints.qos_media_summary import LATEST_TASK_POLL
from litellm.proxy.management_endpoints.qos_sql import sql_list
from litellm.types.llms.base import LiteLLMBaseModel
from litellm.types.qos import (
    QosReviewVideo,
    QosReviewVideoStatus,
    QosVideoAiReview,
    QosVideoAiSummary,
    QosVideoReview,
    QosVideoReviewSummary,
)

QOS_VIDEO_REVIEWS_KEY: Final = "qos_video_reviews"
QOS_VIDEO_AI_REVIEW_KEY: Final = "qos_video_ai_review"
REVIEW_VIDEO_LIMIT: Final = 200
GENERATING_WINDOW: Final = timedelta(hours=3)
PROBE_MADE: Final = f"metadata -> '{QOS_MEDIA_KEY}' ->> 'prompt' IS NOT NULL"
PROBE_RUN: Final = "metadata -> 'spend_logs_metadata' ->> 'qos_probe_run'"
PROBE_SCHEDULED: Final = "COALESCE((metadata -> 'spend_logs_metadata' ->> 'qos_probe_scheduled')::boolean, false)"
CREATED: Final = sql_list(VIDEO_CREATE_CALL_TYPES)

REVIEW_VIDEOS_SQL: Final = f"""
WITH created AS (
    SELECT request_id AS video_id, "startTime" AS created_at, COALESCE(model_group, '') AS model_group,
        metadata -> '{QOS_MEDIA_KEY}' ->> 'task_id' AS task_id,
        metadata -> '{QOS_MEDIA_KEY}' ->> 'prompt' AS prompt,
        {PROBE_RUN} AS run,
        {PROBE_SCHEDULED} AS scheduled,
        COALESCE(metadata -> '{QOS_VIDEO_REVIEWS_KEY}', '{{}}'::jsonb) AS reviews,
        metadata -> '{QOS_VIDEO_AI_REVIEW_KEY}' AS ai_review
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= $1::timestamp AND "startTime" < $2::timestamp
        AND call_type IN ({CREATED})
        AND metadata -> '{QOS_MEDIA_KEY}' ->> 'task_id' IS NOT NULL
        AND {PROBE_MADE}
),
ended AS (
    SELECT metadata -> '{QOS_MEDIA_KEY}' ->> 'task_id' AS task_id,
        MIN("startTime") FILTER (WHERE metadata -> '{QOS_MEDIA_KEY}' ->> 'task_status' = 'success') AS completed_at
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= $1::timestamp AND "startTime" < $2::timestamp + interval '{LATEST_TASK_POLL}'
        AND call_type IN ({sql_list(VIDEO_STATUS_CALL_TYPES)})
        AND metadata -> '{QOS_MEDIA_KEY}' ->> 'task_status' IN ('success', 'failure', 'cancelled')
    GROUP BY 1
)
SELECT created.video_id, created.created_at, created.model_group, created.prompt, created.run, created.scheduled,
    created.reviews,
    created.ai_review, ended.completed_at,
    CASE
        WHEN ended.completed_at IS NOT NULL THEN 'completed'
        WHEN ended.task_id IS NOT NULL THEN 'failed'
        ELSE 'generating'
    END AS status
FROM created LEFT JOIN ended USING (task_id)
WHERE ended.task_id IS NOT NULL OR created.created_at >= $3::timestamp
ORDER BY created.created_at DESC
LIMIT {REVIEW_VIDEO_LIMIT}
"""

REVIEW_SUMMARY_SQL: Final = f"""
SELECT COALESCE(logs.model_group, '') AS model_group,
    COUNT(DISTINCT logs.request_id)::int AS videos,
    COUNT(*)::int AS reviews,
    AVG((review.value ->> 'overall')::float) AS overall,
    AVG((review.value ->> 'visual')::float) AS visual,
    AVG((review.value ->> 'detail')::float) AS detail,
    AVG((review.value ->> 'motion')::float) AS motion,
    AVG((review.value ->> 'alignment')::float) AS alignment,
    AVG((review.value ->> 'physics')::float) AS physics,
    AVG((review.value ->> 'audio')::float) AS audio
FROM "LiteLLM_SpendLogs" AS logs
CROSS JOIN LATERAL jsonb_each(logs.metadata -> '{QOS_VIDEO_REVIEWS_KEY}') AS review
WHERE logs."startTime" >= $1::timestamp AND logs."startTime" < $2::timestamp
    AND logs.call_type IN ({CREATED})
    AND logs.{PROBE_MADE}
    AND jsonb_typeof(logs.metadata -> '{QOS_VIDEO_REVIEWS_KEY}') = 'object'
GROUP BY 1
ORDER BY 1
"""

AI_REVIEW_SUMMARY_SQL: Final = f"""
SELECT COALESCE(model_group, '') AS model_group,
    COUNT(*)::int AS videos,
    AVG((metadata -> '{QOS_VIDEO_AI_REVIEW_KEY}' ->> 'overall')::float) AS overall,
    AVG((metadata -> '{QOS_VIDEO_AI_REVIEW_KEY}' ->> 'visual')::float) AS visual,
    AVG((metadata -> '{QOS_VIDEO_AI_REVIEW_KEY}' ->> 'detail')::float) AS detail,
    AVG((metadata -> '{QOS_VIDEO_AI_REVIEW_KEY}' ->> 'motion')::float) AS motion,
    AVG((metadata -> '{QOS_VIDEO_AI_REVIEW_KEY}' ->> 'alignment')::float) AS alignment,
    AVG((metadata -> '{QOS_VIDEO_AI_REVIEW_KEY}' ->> 'physics')::float) AS physics
FROM "LiteLLM_SpendLogs"
WHERE "startTime" >= $1::timestamp AND "startTime" < $2::timestamp
    AND call_type IN ({CREATED})
    AND {PROBE_MADE}
    AND jsonb_typeof(metadata -> '{QOS_VIDEO_AI_REVIEW_KEY}') = 'object'
GROUP BY 1
ORDER BY 1
"""

RECORD_VIDEO_REVIEW_SQL: Final = f"""
UPDATE "LiteLLM_SpendLogs"
SET metadata = COALESCE(metadata, '{{}}'::jsonb) || jsonb_build_object(
    '{QOS_VIDEO_REVIEWS_KEY}',
    COALESCE(metadata -> '{QOS_VIDEO_REVIEWS_KEY}', '{{}}'::jsonb) || jsonb_build_object($2::text, $3::jsonb)
)
WHERE request_id = $1 AND call_type IN ({CREATED}) AND {PROBE_MADE}
RETURNING request_id
"""

RECORD_AI_REVIEW_SQL: Final = f"""
UPDATE "LiteLLM_SpendLogs"
SET metadata = COALESCE(metadata, '{{}}'::jsonb) || jsonb_build_object('{QOS_VIDEO_AI_REVIEW_KEY}', $2::jsonb)
WHERE request_id = $1 AND call_type IN ({CREATED}) AND {PROBE_MADE}
RETURNING request_id
"""


class ReviewVideoRow(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    video_id: str
    created_at: datetime
    model_group: str
    prompt: str
    run: str | None
    scheduled: bool
    reviews: Mapping[str, QosVideoReview]
    ai_review: QosVideoAiReview | None
    completed_at: datetime | None
    status: QosReviewVideoStatus


class DeploymentCredentials(LiteLLMBaseModel):
    """What fetching a video's file needs from the deployment that generated it."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    api_key: str | None = None
    api_base: str | None = None


class RecordedReview(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str


REVIEW_VIDEO_ROWS: Final = TypeAdapter(tuple[ReviewVideoRow, ...])
REVIEW_SUMMARY_ROWS: Final = TypeAdapter(tuple[QosVideoReviewSummary, ...])
AI_REVIEW_SUMMARY_ROWS: Final = TypeAdapter(tuple[QosVideoAiSummary, ...])
RECORDED_REVIEW_ROWS: Final = TypeAdapter(tuple[RecordedReview, ...])


def review_video(row: ReviewVideoRow, reviewer: str) -> QosReviewVideo:
    overall: Final = tuple(review.overall for review in row.reviews.values())
    return QosReviewVideo(
        video_id=row.video_id,
        model_group=row.model_group,
        status=row.status,
        created_at=row.created_at,
        completed_at=row.completed_at,
        prompt=row.prompt,
        run=row.run,
        scheduled=row.scheduled,
        reviews=len(overall),
        overall=sum(overall) / len(overall) if overall else None,
        my_review=row.reviews.get(reviewer),
        ai_review=row.ai_review,
    )
