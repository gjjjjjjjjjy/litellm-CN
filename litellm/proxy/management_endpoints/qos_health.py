from datetime import datetime
from typing import Final
from urllib.parse import urlparse

from pydantic import ConfigDict, TypeAdapter

from litellm.constants import LITTELM_INTERNAL_HEALTH_SERVICE_ACCOUNT_NAME
from litellm.types.llms.base import LiteLLMBaseModel
from litellm.types.qos import QosHealthNode, QosHealthProbe, QosPercentiles

HEALTH_HISTORY_SQL: Final = """
SELECT
    model_name,
    COALESCE(model_id, '') AS model_id,
    COUNT(*)::int AS checks,
    (COUNT(*) FILTER (WHERE status = 'unhealthy'))::int AS failures,
    (array_agg(status ORDER BY checked_at DESC))[1] AS latest_status,
    (array_agg(error_message ORDER BY checked_at DESC) FILTER (WHERE status = 'unhealthy'))[1] AS last_error,
    MAX(checked_at) FILTER (WHERE status = 'unhealthy') AS last_failure_at,
    MAX(checked_at) AS last_checked_at,
    (array_agg((details->>'qos_ttft_ms')::double precision ORDER BY checked_at DESC)
        FILTER (WHERE details ? 'qos_ttft_ms'))[1] AS last_ttft_ms,
    (array_agg((details->>'qos_latency_ms')::double precision ORDER BY checked_at DESC)
        FILTER (WHERE details ? 'qos_ttft_ms'))[1] AS last_latency_ms,
    MAX(checked_at) FILTER (WHERE details ? 'qos_ttft_ms') AS last_streamed_at
FROM "LiteLLM_HealthCheckTable"
WHERE checked_at >= $1::timestamp AND checked_at < $2::timestamp
GROUP BY model_name, COALESCE(model_id, '')
ORDER BY model_name, model_id
"""

HEALTH_PROBES_SQL: Final = f"""
SELECT
    COALESCE(model, '') AS model,
    RTRIM(COALESCE(api_base, ''), '/') AS api_base,
    COUNT(*)::int AS probes,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(epoch FROM ("endTime" - "startTime")) * 1000) AS p50,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY EXTRACT(epoch FROM ("endTime" - "startTime")) * 1000) AS p95,
    percentile_cont(0.99) WITHIN GROUP (ORDER BY EXTRACT(epoch FROM ("endTime" - "startTime")) * 1000) AS p99,
    MAX("startTime") AS last_probe_at
FROM "LiteLLM_SpendLogs"
WHERE "startTime" >= $1::timestamp
    AND "startTime" < $2::timestamp
    AND request_tags ? '{LITTELM_INTERNAL_HEALTH_SERVICE_ACCOUNT_NAME}'
GROUP BY 1, 2
ORDER BY 2, 1
"""


class HealthHistoryRow(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_name: str
    model_id: str
    checks: int
    failures: int
    latest_status: str
    last_error: str | None
    last_failure_at: datetime | None
    last_checked_at: datetime
    last_ttft_ms: float | None = None
    last_latency_ms: float | None = None
    last_streamed_at: datetime | None = None


class HealthProbeRow(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    api_base: str
    probes: int
    p50: float
    p95: float
    p99: float
    last_probe_at: datetime


class DeploymentTarget(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    api_base: str
    upstream_model: str


HEALTH_HISTORY_ROWS: Final = TypeAdapter(list[HealthHistoryRow])
HEALTH_PROBE_ROWS: Final = TypeAdapter(list[HealthProbeRow])


def probe_key(api_base: str, upstream_model: str) -> tuple[str, str]:
    """Health-check probes are logged without a model id, so they are matched to a node by base URL and model."""
    return api_base.rstrip("/"), upstream_model


_OPENAI_COMPATIBLE_PROVIDERS: Final = frozenset(
    {"openai", "openai_like", "custom_openai", "text-completion-openai", "hosted_vllm", "litellm_proxy"}
)


def vendor_of(provider: str, api_base: str) -> str:
    if provider not in _OPENAI_COMPATIBLE_PROVIDERS:
        return provider
    host: Final = urlparse(api_base).hostname
    if host in {"ai.gitee.com", "api.moark.com"}:
        return "moark"
    return provider if host is None else host


def health_node(row: HealthHistoryRow, target: DeploymentTarget) -> QosHealthNode:
    return QosHealthNode(
        model_name=row.model_name,
        model_id=row.model_id,
        vendor=vendor_of(target.provider, target.api_base),
        api_base=target.api_base,
        upstream_model=target.upstream_model,
        checks=row.checks,
        failures=row.failures,
        availability=(row.checks - row.failures) / row.checks,
        latest_status=row.latest_status,
        last_error=row.last_error,
        last_failure_at=row.last_failure_at,
        last_checked_at=row.last_checked_at,
        last_ttft_ms=row.last_ttft_ms,
        last_latency_ms=row.last_latency_ms,
        last_streamed_at=row.last_streamed_at,
    )


def health_probe(row: HealthProbeRow) -> QosHealthProbe:
    return QosHealthProbe(
        model=row.model,
        api_base=row.api_base,
        probes=row.probes,
        latency_ms=QosPercentiles(p50=row.p50, p95=row.p95, p99=row.p99),
        last_probe_at=row.last_probe_at,
    )
