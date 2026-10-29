"""
Manual video review: finished videos to watch and rate, and the ratings per model.

Ratings live on the video's creation spend log row under `qos_video_reviews`, one entry per reviewer, so they
age out with the rest of service quality data and need no table of their own.
"""

from collections.abc import Mapping
from datetime import datetime
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
from litellm.types.qos import QosReviewVideo, QosVideoReview, QosVideoReviewSummary

QOS_VIDEO_REVIEWS_KEY: Final = "qos_video_reviews"
REVIEW_VIDEO_LIMIT: Final = 200
_CREATED: Final = sql_list(VIDEO_CREATE_CALL_TYPES)

REVIEW_VIDEOS_SQL: Final = f"""
WITH created AS (
    SELECT request_id AS video_id, "startTime" AS created_at, COALESCE(model_group, '') AS model_group,
        metadata -> '{QOS_MEDIA_KEY}' ->> 'task_id' AS task_id,
        metadata -> '{QOS_MEDIA_KEY}' ->> 'prompt' AS prompt,
        COALESCE(metadata -> '{QOS_VIDEO_REVIEWS_KEY}', '{{}}'::jsonb) AS reviews
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= $1::timestamp AND "startTime" < $2::timestamp
        AND call_type IN ({_CREATED})
        AND metadata -> '{QOS_MEDIA_KEY}' ->> 'task_id' IS NOT NULL
),
finished AS (
    SELECT metadata -> '{QOS_MEDIA_KEY}' ->> 'task_id' AS task_id, MIN("startTime") AS completed_at
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= $1::timestamp AND "startTime" < $2::timestamp + interval '{LATEST_TASK_POLL}'
        AND call_type IN ({sql_list(VIDEO_STATUS_CALL_TYPES)})
        AND metadata -> '{QOS_MEDIA_KEY}' ->> 'task_status' = 'success'
    GROUP BY 1
)
SELECT created.video_id, created.created_at, created.model_group, created.prompt, created.reviews,
    finished.completed_at
FROM created JOIN finished USING (task_id)
ORDER BY created.created_at DESC
LIMIT {REVIEW_VIDEO_LIMIT}
"""

REVIEW_SUMMARY_SQL: Final = f"""
SELECT COALESCE(logs.model_group, '') AS model_group,
    COUNT(DISTINCT logs.request_id)::int AS videos,
    COUNT(*)::int AS reviews,
    AVG((review.value ->> 'overall')::float) AS overall,
    AVG((review.value ->> 'visual')::float) AS visual,
    AVG((review.value ->> 'motion')::float) AS motion,
    AVG((review.value ->> 'alignment')::float) AS alignment,
    AVG((review.value ->> 'physics')::float) AS physics,
    AVG((review.value ->> 'audio')::float) AS audio
FROM "LiteLLM_SpendLogs" AS logs
CROSS JOIN LATERAL jsonb_each(logs.metadata -> '{QOS_VIDEO_REVIEWS_KEY}') AS review
WHERE logs."startTime" >= $1::timestamp AND logs."startTime" < $2::timestamp
    AND logs.call_type IN ({_CREATED})
    AND jsonb_typeof(logs.metadata -> '{QOS_VIDEO_REVIEWS_KEY}') = 'object'
GROUP BY 1
ORDER BY 1
"""

RECORD_VIDEO_REVIEW_SQL: Final = f"""
UPDATE "LiteLLM_SpendLogs"
SET metadata = COALESCE(metadata, '{{}}'::jsonb) || jsonb_build_object(
    '{QOS_VIDEO_REVIEWS_KEY}',
    COALESCE(metadata -> '{QOS_VIDEO_REVIEWS_KEY}', '{{}}'::jsonb) || jsonb_build_object($2::text, $3::jsonb)
)
WHERE request_id = $1 AND call_type IN ({_CREATED})
RETURNING request_id
"""


class ReviewVideoRow(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    video_id: str
    created_at: datetime
    model_group: str
    prompt: str | None
    reviews: Mapping[str, QosVideoReview]
    completed_at: datetime


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
RECORDED_REVIEW_ROWS: Final = TypeAdapter(tuple[RecordedReview, ...])


def review_video(row: ReviewVideoRow, reviewer: str) -> QosReviewVideo:
    overall: Final = tuple(review.overall for review in row.reviews.values())
    return QosReviewVideo(
        video_id=row.video_id,
        model_group=row.model_group,
        created_at=row.created_at,
        completed_at=row.completed_at,
        prompt=row.prompt,
        reviews=len(overall),
        overall=sum(overall) / len(overall) if overall else None,
        my_review=row.reviews.get(reviewer),
    )
