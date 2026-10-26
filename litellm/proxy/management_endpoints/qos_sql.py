"""SQL fragments that define the QoS metrics, shared by every query that reports them."""

from typing import Final

from litellm.constants import LITTELM_INTERNAL_HEALTH_SERVICE_ACCOUNT_NAME
from litellm.proxy.management_endpoints.qos_response_check import RESPONSE_CHECK_KEY

TTFT_MS: Final = """CASE
            WHEN status IS DISTINCT FROM 'failure'
                AND "completionStartTime" IS NOT NULL
                AND "completionStartTime" <> "endTime"
            THEN EXTRACT(epoch FROM ("completionStartTime" - "startTime")) * 1000
        END"""

TPOT_MS: Final = """CASE
            WHEN status IS DISTINCT FROM 'failure'
                AND "completionStartTime" IS NOT NULL
                AND "completionStartTime" <> "endTime"
                AND completion_tokens > 1
            THEN EXTRACT(epoch FROM ("endTime" - "completionStartTime")) * 1000 / (completion_tokens - 1)
        END"""

MODEL_TRAFFIC: Final = f"""COALESCE(cache_hit, '') <> 'True'
        AND COALESCE(model, '') <> ''
        AND NOT COALESCE(request_tags ? '{LITTELM_INTERNAL_HEALTH_SERVICE_ACCOUNT_NAME}', false)"""

RESPONSE_CHECK: Final = f"metadata->>'{RESPONSE_CHECK_KEY}'"


def logged_model_group(deployment_groups_param: str) -> str:
    """A request that addressed a deployment by id is logged with the id as its model group; report its model name."""
    return (
        f"CASE WHEN {deployment_groups_param}::jsonb ? model_group "
        f"THEN {deployment_groups_param}::jsonb ->> model_group ELSE COALESCE(model_group, '') END"
    )
