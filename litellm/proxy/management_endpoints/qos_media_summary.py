"""
Service quality of audio and video models over a window: how long speech and transcription take against the length
of the audio, and how video tasks end and how long they queue and run.

A row is classified by its call type. Failure rows written by the proxy carry no call type, so those fall back to the
mode configured on the deployment that served them.
"""

import json
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from pydantic import ConfigDict, TypeAdapter

from litellm.proxy.management_endpoints.qos_media import (
    QOS_MEDIA_KEY,
    SPEECH_CALL_TYPES,
    TRANSCRIPTION_CALL_TYPES,
    VIDEO_CREATE_CALL_TYPES,
    VIDEO_STATUS_CALL_TYPES,
)
from litellm.proxy.management_endpoints.qos_sql import MODEL_TRAFFIC, logged_model_group, sql_list
from litellm.types.llms.base import LiteLLMBaseModel
from litellm.types.qos import QosAudioMetrics, QosPercentiles, QosVideoMetrics

if TYPE_CHECKING:
    from litellm.router import Router

_MODALITY_OF_MODE: Final = MappingProxyType(
    {"audio_speech": "speech", "audio_transcription": "transcription", "video_generation": "video"}
)
_LATEST_TASK_POLL: Final = "1 day"


def _media_field(field: str, sql_type: str) -> str:
    return f"(metadata -> '{QOS_MEDIA_KEY}' ->> '{field}')::{sql_type}"


_MODALITY: Final = f"""COALESCE(
            CASE
                WHEN call_type IN ({sql_list(SPEECH_CALL_TYPES)}) THEN 'speech'
                WHEN call_type IN ({sql_list(TRANSCRIPTION_CALL_TYPES)}) THEN 'transcription'
                WHEN call_type IN ({sql_list(VIDEO_CREATE_CALL_TYPES)}) THEN 'video'
                WHEN COALESCE(call_type, '') <> '' THEN 'other'
            END,
            $3::jsonb ->> COALESCE(model_id, '')
        )"""

AUDIO_SUMMARY_SQL: Final = f"""
WITH base AS (
    SELECT
        {logged_model_group("$4")} AS model_group,
        {_MODALITY} AS modality,
        status,
        EXTRACT(epoch FROM ("endTime" - "startTime")) * 1000 AS latency_ms,
        {_media_field("audio_seconds", "float")} AS audio_seconds,
        {_media_field("input_chars", "int")} AS input_chars
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= $1::timestamp
        AND "startTime" < $2::timestamp
        AND {MODEL_TRAFFIC}
),
served AS (
    SELECT
        *,
        CASE WHEN status IS DISTINCT FROM 'failure' THEN latency_ms END AS served_ms,
        CASE
            WHEN status IS DISTINCT FROM 'failure' AND audio_seconds > 0 THEN latency_ms / (audio_seconds * 1000)
        END AS real_time_factor
    FROM base
    WHERE modality IN ('speech', 'transcription')
)
SELECT
    model_group,
    MAX(modality) AS modality,
    COUNT(*)::int AS requests,
    (COUNT(*) FILTER (WHERE status = 'failure'))::int AS failed_requests,
    COALESCE(SUM(audio_seconds) FILTER (WHERE status IS DISTINCT FROM 'failure'), 0)::float AS audio_seconds,
    COALESCE(SUM(input_chars) FILTER (WHERE status IS DISTINCT FROM 'failure'), 0)::int AS input_chars,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY served_ms) AS latency_p50,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY served_ms) AS latency_p95,
    percentile_cont(0.99) WITHIN GROUP (ORDER BY served_ms) AS latency_p99,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY real_time_factor) AS rtf_p50,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY real_time_factor) AS rtf_p95,
    percentile_cont(0.99) WITHIN GROUP (ORDER BY real_time_factor) AS rtf_p99
FROM served
GROUP BY model_group
ORDER BY model_group
"""

VIDEO_SUMMARY_SQL: Final = f"""
WITH created AS (
    SELECT
        {logged_model_group("$4")} AS model_group,
        status,
        metadata -> '{QOS_MEDIA_KEY}' ->> 'task_id' AS task_id
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= $1::timestamp
        AND "startTime" < $2::timestamp
        AND {MODEL_TRAFFIC}
        AND {_MODALITY} = 'video'
),
finished AS (
    SELECT DISTINCT ON (metadata -> '{QOS_MEDIA_KEY}' ->> 'task_id')
        metadata -> '{QOS_MEDIA_KEY}' ->> 'task_id' AS task_id,
        metadata -> '{QOS_MEDIA_KEY}' ->> 'task_status' AS task_status,
        {_media_field("queue_ms", "float")} AS queue_ms,
        {_media_field("run_ms", "float")} AS run_ms,
        {_media_field("task_price", "float")} AS task_price
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= $1::timestamp
        AND "startTime" < $2::timestamp + interval '{_LATEST_TASK_POLL}'
        AND call_type IN ({sql_list(VIDEO_STATUS_CALL_TYPES)})
        AND metadata -> '{QOS_MEDIA_KEY}' ->> 'task_status' IN ('success', 'failure', 'cancelled')
    ORDER BY metadata -> '{QOS_MEDIA_KEY}' ->> 'task_id', "startTime" DESC
)
SELECT
    created.model_group,
    COUNT(*)::int AS submitted,
    (COUNT(*) FILTER (WHERE created.status = 'failure'))::int AS failed_submissions,
    (COUNT(*) FILTER (WHERE finished.task_status = 'success'))::int AS succeeded,
    (COUNT(*) FILTER (WHERE finished.task_status = 'failure'))::int AS failed,
    (COUNT(*) FILTER (WHERE finished.task_status = 'cancelled'))::int AS cancelled,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY finished.queue_ms) AS queue_p50,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY finished.queue_ms) AS queue_p95,
    percentile_cont(0.99) WITHIN GROUP (ORDER BY finished.queue_ms) AS queue_p99,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY finished.run_ms) FILTER (WHERE finished.task_status = 'success')
        AS run_p50,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY finished.run_ms) FILTER (WHERE finished.task_status = 'success')
        AS run_p95,
    percentile_cont(0.99) WITHIN GROUP (ORDER BY finished.run_ms) FILTER (WHERE finished.task_status = 'success')
        AS run_p99,
    SUM(finished.task_price)::float AS task_price
FROM created
LEFT JOIN finished USING (task_id)
GROUP BY created.model_group
ORDER BY created.model_group
"""


class AudioRow(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_group: str
    modality: Literal["speech", "transcription"]
    requests: int
    failed_requests: int
    audio_seconds: float
    input_chars: int
    latency_p50: float | None
    latency_p95: float | None
    latency_p99: float | None
    rtf_p50: float | None
    rtf_p95: float | None
    rtf_p99: float | None


class VideoRow(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_group: str
    submitted: int
    failed_submissions: int
    succeeded: int
    failed: int
    cancelled: int
    queue_p50: float | None
    queue_p95: float | None
    queue_p99: float | None
    run_p50: float | None
    run_p95: float | None
    run_p99: float | None
    task_price: float | None


AUDIO_ROWS: Final = TypeAdapter(list[AudioRow])
VIDEO_ROWS: Final = TypeAdapter(list[VideoRow])


def deployment_modalities(llm_router: "Router | None") -> str:
    """The audio or video modality of each deployment configured with one, keyed by model id, as JSON."""
    if llm_router is None:
        return "{}"
    return json.dumps(
        {
            model_id: _MODALITY_OF_MODE[mode]
            for model_id in llm_router.get_model_ids()
            if (deployment := llm_router.get_deployment(model_id)) is not None
            and (mode := deployment.model_info.get("mode")) in _MODALITY_OF_MODE
        }
    )


def audio_metrics(row: AudioRow) -> QosAudioMetrics:
    return QosAudioMetrics(
        model_group=row.model_group,
        modality=row.modality,
        requests=row.requests,
        failed_requests=row.failed_requests,
        audio_seconds=row.audio_seconds,
        input_chars=row.input_chars,
        latency_ms=QosPercentiles(p50=row.latency_p50, p95=row.latency_p95, p99=row.latency_p99),
        real_time_factor=QosPercentiles(p50=row.rtf_p50, p95=row.rtf_p95, p99=row.rtf_p99),
    )


def video_metrics(row: VideoRow) -> QosVideoMetrics:
    return QosVideoMetrics(
        model_group=row.model_group,
        submitted=row.submitted,
        failed_submissions=row.failed_submissions,
        succeeded=row.succeeded,
        failed=row.failed,
        cancelled=row.cancelled,
        queue_ms=QosPercentiles(p50=row.queue_p50, p95=row.queue_p95, p99=row.queue_p99),
        run_ms=QosPercentiles(p50=row.run_p50, p95=row.run_p95, p99=row.run_p99),
        task_price=row.task_price,
    )
