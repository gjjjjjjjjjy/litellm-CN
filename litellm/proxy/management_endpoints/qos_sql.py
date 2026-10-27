"""SQL fragments that define the QoS metrics, shared by every query that reports them."""

from collections.abc import Collection
from typing import Final

from litellm.constants import LITTELM_INTERNAL_HEALTH_SERVICE_ACCOUNT_NAME
from litellm.proxy.management_endpoints.qos_media import (
    SPEECH_CALL_TYPES,
    TRANSCRIPTION_CALL_TYPES,
    VIDEO_CREATE_CALL_TYPES,
    VIDEO_STATUS_CALL_TYPES,
)
from litellm.proxy.management_endpoints.qos_response_check import RESPONSE_CHECK_KEY


def sql_list(values: Collection[str]) -> str:
    """Constant identifiers as a SQL list, for IN clauses. Only for values defined in code, never caller input."""
    return ", ".join(f"'{value}'" for value in sorted(values))


_NO_TOKEN_STREAM: Final = sql_list(
    SPEECH_CALL_TYPES
    | TRANSCRIPTION_CALL_TYPES
    | VIDEO_CREATE_CALL_TYPES
    | {"image_generation", "aimage_generation", "image_edit", "aimage_edit"}
)

TTFT_MS: Final = f"""CASE
            WHEN status IS DISTINCT FROM 'failure'
                AND "completionStartTime" IS NOT NULL
                AND "completionStartTime" <> "endTime"
                AND COALESCE(call_type, '') NOT IN ({_NO_TOKEN_STREAM})
            THEN EXTRACT(epoch FROM ("completionStartTime" - "startTime")) * 1000
        END"""

TPOT_MS: Final = f"""CASE
            WHEN status IS DISTINCT FROM 'failure'
                AND "completionStartTime" IS NOT NULL
                AND "completionStartTime" <> "endTime"
                AND COALESCE(call_type, '') NOT IN ({_NO_TOKEN_STREAM})
                AND completion_tokens > 1
            THEN EXTRACT(epoch FROM ("endTime" - "completionStartTime")) * 1000 / (completion_tokens - 1)
        END"""

VIDEO_POLL_CALL_TYPES: Final = VIDEO_STATUS_CALL_TYPES | {
    "video_content",
    "avideo_content",
    "video_list",
    "avideo_list",
    "video_retrieve_job",
    "avideo_retrieve_job",
}

MODEL_TRAFFIC: Final = f"""COALESCE(cache_hit, '') <> 'True'
        AND COALESCE(model, '') <> ''
        AND NOT COALESCE(request_tags ? '{LITTELM_INTERNAL_HEALTH_SERVICE_ACCOUNT_NAME}', false)
        AND COALESCE(call_type, '') NOT IN ({sql_list(VIDEO_POLL_CALL_TYPES)})"""

RESPONSE_CHECK: Final = f"metadata->>'{RESPONSE_CHECK_KEY}'"


def logged_model_group(deployment_groups_param: str) -> str:
    """A request that addressed a deployment by id is logged with the id as its model group; report its model name."""
    return (
        f"CASE WHEN {deployment_groups_param}::jsonb ? model_group "
        f"THEN {deployment_groups_param}::jsonb ->> model_group ELSE COALESCE(model_group, '') END"
    )
