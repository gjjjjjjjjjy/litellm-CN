"""Service quality summaries: time windows, the queries over spend logs and how their rows become metrics."""

from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Final

from fastapi import HTTPException
from pydantic import ConfigDict, TypeAdapter

from litellm.proxy.management_endpoints.qos_health import vendor_of
from litellm.proxy.management_endpoints.qos_sql import (
    MODEL_TRAFFIC,
    RESPONSE_CHECK,
    TPOT_MS,
    TTFT_MS,
    logged_model_group,
)
from litellm.types.llms.base import LiteLLMBaseModel
from litellm.types.qos import (
    QosBenchmarkRun,
    QosDeploymentMetrics,
    QosInterference,
    QosModelGroupMetrics,
    QosPercentiles,
    QosResponseChecks,
)

QOS_DEFAULT_WINDOW: Final = timedelta(hours=24)
QOS_MAX_WINDOW: Final = timedelta(days=31)
QOS_RUNS_DEFAULT_WINDOW: Final = timedelta(days=7)

HISTORY_START_SQL: Final = """
SELECT MIN(start_time) AS start_time
FROM (
    SELECT MIN("startTime") AS start_time FROM "LiteLLM_SpendLogs" WHERE "startTime" < $1::timestamp
    UNION ALL
    SELECT MIN(checked_at) AS start_time FROM "LiteLLM_HealthCheckTable" WHERE checked_at < $1::timestamp
) AS history
"""


class HistoryStart(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    start_time: datetime | None


HISTORY_START_ROWS: Final = TypeAdapter(tuple[HistoryStart])

BENCHMARK_DELETE_SQL: Final = """
WITH deleted AS (
    DELETE FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= $1::timestamp AND request_tags ? $2::text
    RETURNING request_id
),
deleted_tool_index AS (
    DELETE FROM "LiteLLM_SpendLogToolIndex" WHERE request_id IN (SELECT request_id FROM deleted)
),
deleted_guardrail_index AS (
    DELETE FROM "LiteLLM_SpendLogGuardrailIndex" WHERE request_id IN (SELECT request_id FROM deleted)
)
SELECT COUNT(*)::int AS deleted_requests FROM deleted
"""


BENCHMARK_RUNS_SQL: Final = f"""
SELECT
    run_tag AS run_id,
    MAX({logged_model_group("$3")}) AS model_group,
    COUNT(*)::int AS requests,
    (COUNT(*) FILTER (WHERE status = 'failure'))::int AS failed_requests,
    (COUNT(*) FILTER (WHERE {RESPONSE_CHECK} = 'crosstalk'))::int AS crosstalk_responses,
    MIN("startTime") AS started_at,
    MAX("endTime") AS last_response_at
FROM "LiteLLM_SpendLogs"
CROSS JOIN LATERAL jsonb_array_elements_text(
    CASE WHEN jsonb_typeof(request_tags) = 'array' THEN request_tags ELSE '[]'::jsonb END
) AS run_tag
WHERE "startTime" >= $1::timestamp
    AND "startTime" < $2::timestamp
    AND left(run_tag, 4) = 'qos-'
    AND strpos(run_tag, '@c') = 0
GROUP BY run_tag
ORDER BY started_at DESC
LIMIT 100
"""

_SUMMARY_SQL: Final = """
WITH base AS (
    SELECT
        {model_group} AS model_group,
        COALESCE(model_id, '') AS model_id,
        COALESCE(model, '') AS model,
        COALESCE(api_base, '') AS api_base,
        COALESCE(custom_llm_provider, '') AS custom_llm_provider,
        status,
        "startTime" AS started,
        "endTime" AS ended,
        completion_tokens,
        {response_check} AS response_check,
        EXTRACT(epoch FROM ("endTime" - "startTime")) * 1000 AS e2e_ms,
        {ttft_ms} AS ttft_ms,
        {tpot_ms} AS tpot_ms{level_column}
    FROM {source}
    WHERE "startTime" >= $1::timestamp
        AND "startTime" < $2::timestamp
        AND {model_traffic}
        AND ($3::text IS NULL OR {model_group} = $3::text)
        AND {tag_filter}
),
events AS (
    SELECT {keys}, started AS at, 1 AS delta FROM base
    UNION ALL
    SELECT {keys}, ended AS at, -1 AS delta FROM base
),
running AS (
    SELECT {keys}, SUM(delta) OVER (PARTITION BY {keys} ORDER BY at, delta ROWS UNBOUNDED PRECEDING) AS in_flight
    FROM events
),
peaks AS (
    SELECT {keys}, MAX(in_flight) AS peak_concurrency FROM running GROUP BY {keys}
)
SELECT
    {selected_keys},
    MAX(base.model) AS model,
    MAX(base.api_base) AS api_base,
    MAX(base.custom_llm_provider) AS custom_llm_provider,
    COUNT(*)::int AS requests,
    (COUNT(*) FILTER (WHERE base.status = 'failure'))::int AS failed_requests,
    COUNT(base.ttft_ms)::int AS streamed_requests,
    COALESCE(SUM(base.completion_tokens) FILTER (WHERE base.status IS DISTINCT FROM 'failure'), 0)::int AS output_tokens,
    MAX(peaks.peak_concurrency)::int AS peak_concurrency,
    MIN(base.started) AS first_request_at,
    MAX(base.ended) AS last_response_at,
    COUNT(base.response_check)::int AS checked_responses,
    (COUNT(*) FILTER (WHERE base.response_check = 'crosstalk'))::int AS crosstalk_responses,
    (COUNT(*) FILTER (WHERE base.response_check = 'marker_missing'))::int AS marker_missing_responses,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY base.ttft_ms) AS ttft_p50,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY base.ttft_ms) AS ttft_p95,
    percentile_cont(0.99) WITHIN GROUP (ORDER BY base.ttft_ms) AS ttft_p99,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY base.tpot_ms) AS tpot_p50,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY base.tpot_ms) AS tpot_p95,
    percentile_cont(0.99) WITHIN GROUP (ORDER BY base.tpot_ms) AS tpot_p99,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY base.e2e_ms) AS e2e_p50,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY base.e2e_ms) AS e2e_p95,
    percentile_cont(0.99) WITHIN GROUP (ORDER BY base.e2e_ms) AS e2e_p99
FROM base
JOIN peaks USING ({keys})
GROUP BY {selected_keys}
ORDER BY {selected_keys}
"""

_SPEND_LOGS: Final = '"LiteLLM_SpendLogs"'
_REQUEST_TAG_FILTER: Final = "($4::text IS NULL OR request_tags ? $4::text)"
_SUMMARY_FRAGMENTS: Final = MappingProxyType(
    {
        "model_group": logged_model_group("$5"),
        "response_check": RESPONSE_CHECK,
        "ttft_ms": TTFT_MS,
        "tpot_ms": TPOT_MS,
        "model_traffic": MODEL_TRAFFIC,
    }
)
_LEVEL_SOURCE: Final = (
    _SPEND_LOGS
    + " CROSS JOIN LATERAL jsonb_array_elements_text("
    + "CASE WHEN jsonb_typeof(request_tags) = 'array' THEN request_tags ELSE '[]'::jsonb END) AS level_tag"
)
_LEVEL_TAG_FILTER: Final = "left(level_tag, length($4::text) + 2) = $4::text || '@c'"

DEPLOYMENT_SUMMARY_SQL: Final = _SUMMARY_SQL.format(
    keys="model_group, model_id",
    selected_keys="base.model_group, base.model_id",
    level_column="",
    **_SUMMARY_FRAGMENTS,
    source=_SPEND_LOGS,
    tag_filter=_REQUEST_TAG_FILTER,
)
MODEL_GROUP_SUMMARY_SQL: Final = _SUMMARY_SQL.format(
    keys="model_group",
    selected_keys="base.model_group",
    level_column="",
    **_SUMMARY_FRAGMENTS,
    source=_SPEND_LOGS,
    tag_filter=_REQUEST_TAG_FILTER,
)
BENCHMARK_LEVEL_SUMMARY_SQL: Final = _SUMMARY_SQL.format(
    keys="model_group, level_tag",
    selected_keys="base.model_group, base.level_tag",
    level_column=",\n        level_tag",
    **_SUMMARY_FRAGMENTS,
    source=_LEVEL_SOURCE,
    tag_filter=_LEVEL_TAG_FILTER,
)
BENCHMARK_DEPLOYMENT_LEVEL_SUMMARY_SQL: Final = _SUMMARY_SQL.format(
    keys="model_group, model_id, level_tag",
    selected_keys="base.model_group, base.model_id, base.level_tag",
    level_column=",\n        level_tag",
    **_SUMMARY_FRAGMENTS,
    source=_LEVEL_SOURCE,
    tag_filter=_LEVEL_TAG_FILTER,
)

_LONGEST_OVERLAPPING_REQUEST: Final = "1 hour"
BENCHMARK_INTERFERENCE_SQL: Final = f"""
WITH run_levels AS (
    SELECT
        COALESCE(model_id, '') AS model_id,
        level_tag,
        MAX(COALESCE(api_base, '')) AS api_base,
        MIN("startTime") AS level_start,
        MAX("endTime") AS level_end
    FROM {_LEVEL_SOURCE}
    WHERE "startTime" >= $1::timestamp
        AND "startTime" < $2::timestamp
        AND left(level_tag, length($3::text) + 2) = $3::text || '@c'
    GROUP BY 1, 2
)
SELECT
    run_levels.model_id,
    run_levels.level_tag,
    (COUNT(other.request_id) FILTER (WHERE COALESCE(other.model_id, '') = run_levels.model_id))::int AS same_deployment,
    (COUNT(other.request_id) FILTER (WHERE COALESCE(other.model_id, '') <> run_levels.model_id))::int AS same_endpoint
FROM run_levels
LEFT JOIN {_SPEND_LOGS} AS other
    ON other."startTime" >= run_levels.level_start - interval '{_LONGEST_OVERLAPPING_REQUEST}'
    AND other."startTime" < run_levels.level_end
    AND other."endTime" > run_levels.level_start
    AND NOT COALESCE(other.request_tags ? $3::text, false)
    AND (
        COALESCE(other.model_id, '') = run_levels.model_id
        OR (run_levels.api_base <> '' AND COALESCE(other.api_base, '') = run_levels.api_base)
    )
GROUP BY run_levels.model_id, run_levels.level_tag
"""


class QosSummaryRow(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_group: str
    model_id: str = ""
    level_tag: str = ""
    model: str
    api_base: str
    custom_llm_provider: str
    requests: int
    failed_requests: int
    streamed_requests: int
    output_tokens: int
    peak_concurrency: int
    first_request_at: datetime
    last_response_at: datetime
    checked_responses: int
    crosstalk_responses: int
    marker_missing_responses: int
    ttft_p50: float | None
    ttft_p95: float | None
    ttft_p99: float | None
    tpot_p50: float | None
    tpot_p95: float | None
    tpot_p99: float | None
    e2e_p50: float | None
    e2e_p95: float | None
    e2e_p99: float | None


class InterferenceRow(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    level_tag: str
    same_deployment: int
    same_endpoint: int


SUMMARY_ROWS: Final = TypeAdapter(list[QosSummaryRow])
INTERFERENCE_ROWS: Final = TypeAdapter(list[InterferenceRow])
BENCHMARK_RUNS: Final = TypeAdapter(list[QosBenchmarkRun])


def as_utc_naive(value: datetime) -> datetime:
    return value if value.tzinfo is None else value.astimezone(timezone.utc).replace(tzinfo=None)


def resolve_window(
    start_time: datetime | None,
    end_time: datetime | None,
    now: datetime,
    default_window: timedelta = QOS_DEFAULT_WINDOW,
) -> tuple[datetime, datetime]:
    end: Final = as_utc_naive(end_time) if end_time is not None else now
    start: Final = as_utc_naive(start_time) if start_time is not None else end - default_window
    if start >= end:
        raise HTTPException(status_code=400, detail="start_time must be earlier than end_time")
    if end - start > QOS_MAX_WINDOW:
        raise HTTPException(status_code=400, detail=f"The time window must not exceed {QOS_MAX_WINDOW.days} days")
    return start, end


def group_metrics(row: QosSummaryRow) -> QosModelGroupMetrics:
    active_seconds: Final = (row.last_response_at - row.first_request_at).total_seconds()
    return QosModelGroupMetrics(
        model_group=row.model_group,
        requests=row.requests,
        failed_requests=row.failed_requests,
        streamed_requests=row.streamed_requests,
        output_tokens=row.output_tokens,
        peak_concurrency=row.peak_concurrency,
        first_request_at=row.first_request_at,
        last_response_at=row.last_response_at,
        requests_per_second=row.requests / active_seconds if active_seconds > 0 else 0.0,
        output_tokens_per_second=row.output_tokens / active_seconds if active_seconds > 0 else 0.0,
        ttft_ms=QosPercentiles(p50=row.ttft_p50, p95=row.ttft_p95, p99=row.ttft_p99),
        tpot_ms=QosPercentiles(p50=row.tpot_p50, p95=row.tpot_p95, p99=row.tpot_p99),
        e2e_latency_ms=QosPercentiles(p50=row.e2e_p50, p95=row.e2e_p95, p99=row.e2e_p99),
        response_checks=QosResponseChecks(
            checked=row.checked_responses,
            crosstalk=row.crosstalk_responses,
            marker_missing=row.marker_missing_responses,
        ),
    )


def deployment_interference(row: InterferenceRow) -> QosInterference:
    return QosInterference(same_deployment=row.same_deployment, same_endpoint=row.same_endpoint)


def level_interference(level_tag: str, rows: list[InterferenceRow]) -> QosInterference:
    """A level's outside traffic summed over the deployments it ran on."""
    at_level: Final = tuple(row for row in rows if row.level_tag == level_tag)
    return QosInterference(
        same_deployment=sum(row.same_deployment for row in at_level),
        same_endpoint=sum(row.same_endpoint for row in at_level),
    )


def deployment_metrics(row: QosSummaryRow) -> QosDeploymentMetrics:
    return QosDeploymentMetrics(
        **group_metrics(row).model_dump(),
        model_id=row.model_id,
        model=row.model,
        api_base=row.api_base,
        vendor=vendor_of(row.custom_llm_provider, row.api_base),
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
