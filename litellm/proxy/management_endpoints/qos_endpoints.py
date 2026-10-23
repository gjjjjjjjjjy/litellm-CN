import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ConfigDict, TypeAdapter

from litellm.proxy._types import CommonProxyErrors, LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.management_endpoints.qos_benchmark import QOS_RUN_PREFIX, concurrency_of, new_run_id, start_benchmark
from litellm.types.llms.base import LiteLLMBaseModel
from litellm.types.qos import (
    QosBenchmarkDetail,
    QosBenchmarkLevel,
    QosBenchmarkListResponse,
    QosBenchmarkRequest,
    QosBenchmarkRun,
    QosBenchmarkStarted,
    QosDeploymentMetrics,
    QosModelGroupMetrics,
    QosPercentiles,
    QosSummaryResponse,
)

router: Final = APIRouter()

QOS_DEFAULT_WINDOW: Final = timedelta(hours=24)
QOS_MAX_WINDOW: Final = timedelta(days=31)
QOS_RUNS_DEFAULT_WINDOW: Final = timedelta(days=7)
_RUN_ID: Final = re.compile(rf"{QOS_RUN_PREFIX}[A-Za-z0-9.-]+")

BENCHMARK_RUNS_SQL: Final = """
SELECT
    run_tag AS run_id,
    MAX(COALESCE(model_group, '')) AS model_group,
    COUNT(*)::int AS requests,
    (COUNT(*) FILTER (WHERE status = 'failure'))::int AS failed_requests,
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
        COALESCE(model_group, '') AS model_group,
        COALESCE(model_id, '') AS model_id,
        COALESCE(model, '') AS model,
        COALESCE(api_base, '') AS api_base,
        status,
        "startTime" AS started,
        "endTime" AS ended,
        completion_tokens,
        EXTRACT(epoch FROM ("endTime" - "startTime")) * 1000 AS e2e_ms,
        CASE
            WHEN status IS DISTINCT FROM 'failure'
                AND "completionStartTime" IS NOT NULL
                AND "completionStartTime" <> "endTime"
            THEN EXTRACT(epoch FROM ("completionStartTime" - "startTime")) * 1000
        END AS ttft_ms,
        CASE
            WHEN status IS DISTINCT FROM 'failure'
                AND "completionStartTime" IS NOT NULL
                AND "completionStartTime" <> "endTime"
                AND completion_tokens > 1
            THEN EXTRACT(epoch FROM ("endTime" - "completionStartTime")) * 1000 / (completion_tokens - 1)
        END AS tpot_ms{level_column}
    FROM {source}
    WHERE "startTime" >= $1::timestamp
        AND "startTime" < $2::timestamp
        AND COALESCE(cache_hit, '') <> 'True'
        AND ($3::text IS NULL OR model_group = $3::text)
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
    COUNT(*)::int AS requests,
    (COUNT(*) FILTER (WHERE base.status = 'failure'))::int AS failed_requests,
    COUNT(base.ttft_ms)::int AS streamed_requests,
    COALESCE(SUM(base.completion_tokens) FILTER (WHERE base.status IS DISTINCT FROM 'failure'), 0)::int AS output_tokens,
    MAX(peaks.peak_concurrency)::int AS peak_concurrency,
    MIN(base.started) AS first_request_at,
    MAX(base.ended) AS last_response_at,
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

DEPLOYMENT_SUMMARY_SQL: Final = _SUMMARY_SQL.format(
    keys="model_group, model_id",
    selected_keys="base.model_group, base.model_id",
    level_column="",
    source=_SPEND_LOGS,
    tag_filter=_REQUEST_TAG_FILTER,
)
MODEL_GROUP_SUMMARY_SQL: Final = _SUMMARY_SQL.format(
    keys="model_group",
    selected_keys="base.model_group",
    level_column="",
    source=_SPEND_LOGS,
    tag_filter=_REQUEST_TAG_FILTER,
)
BENCHMARK_LEVEL_SUMMARY_SQL: Final = _SUMMARY_SQL.format(
    keys="model_group, level_tag",
    selected_keys="base.model_group, base.level_tag",
    level_column=",\n        level_tag",
    source=_SPEND_LOGS
    + " CROSS JOIN LATERAL jsonb_array_elements_text("
    + "CASE WHEN jsonb_typeof(request_tags) = 'array' THEN request_tags ELSE '[]'::jsonb END) AS level_tag",
    tag_filter="left(level_tag, length($4::text) + 2) = $4::text || '@c'",
)


class QosSummaryRow(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_group: str
    model_id: str = ""
    level_tag: str = ""
    model: str
    api_base: str
    requests: int
    failed_requests: int
    streamed_requests: int
    output_tokens: int
    peak_concurrency: int
    first_request_at: datetime
    last_response_at: datetime
    ttft_p50: float | None
    ttft_p95: float | None
    ttft_p99: float | None
    tpot_p50: float | None
    tpot_p95: float | None
    tpot_p99: float | None
    e2e_p50: float | None
    e2e_p95: float | None
    e2e_p99: float | None


_ROWS: Final = TypeAdapter(list[QosSummaryRow])
_RUNS: Final = TypeAdapter(list[QosBenchmarkRun])


def _as_utc_naive(value: datetime) -> datetime:
    return value if value.tzinfo is None else value.astimezone(timezone.utc).replace(tzinfo=None)


def resolve_window(
    start_time: datetime | None,
    end_time: datetime | None,
    now: datetime,
    default_window: timedelta = QOS_DEFAULT_WINDOW,
) -> tuple[datetime, datetime]:
    end: Final = _as_utc_naive(end_time) if end_time is not None else now
    start: Final = _as_utc_naive(start_time) if start_time is not None else end - default_window
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
    )


def deployment_metrics(row: QosSummaryRow) -> QosDeploymentMetrics:
    return QosDeploymentMetrics(
        **group_metrics(row).model_dump(), model_id=row.model_id, model=row.model, api_base=row.api_base
    )


@router.get(
    "/qos/summary",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosSummaryResponse,
)
async def get_qos_summary(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    start_time: Annotated[datetime | None, Query(description="ISO 8601, defaults to 24 hours before end_time")] = None,
    end_time: Annotated[datetime | None, Query(description="ISO 8601, defaults to now")] = None,
    model_group: Annotated[str | None, Query(description="Only include this public model name")] = None,
    tag: Annotated[str | None, Query(description="Only include requests carrying this request tag")] = None,
) -> QosSummaryResponse:
    from litellm.proxy.proxy_server import prisma_client

    if user_api_key_dict.user_role not in (LitellmUserRoles.PROXY_ADMIN, LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY):
        raise HTTPException(status_code=403, detail="Only proxy admins can view service quality metrics")
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)

    start, end = resolve_window(start_time, end_time, datetime.now(timezone.utc).replace(tzinfo=None))
    group_rows: Final = _ROWS.validate_python(
        await prisma_client.db.query_raw(MODEL_GROUP_SUMMARY_SQL, start, end, model_group, tag)
    )
    deployment_rows: Final = _ROWS.validate_python(
        await prisma_client.db.query_raw(DEPLOYMENT_SUMMARY_SQL, start, end, model_group, tag)
    )
    return QosSummaryResponse(
        start_time=start,
        end_time=end,
        tag=tag,
        model_groups=tuple(group_metrics(row) for row in group_rows),
        deployments=tuple(deployment_metrics(row) for row in deployment_rows),
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _require_role(user_api_key_dict: UserAPIKeyAuth, roles: tuple[LitellmUserRoles, ...]) -> None:
    if user_api_key_dict.user_role not in roles:
        raise HTTPException(status_code=403, detail="Only proxy admins can run or view QoS benchmarks")


def _loopback_base_url(request: Request) -> str:
    port: Final = request.scope["server"][1]
    return f"http://127.0.0.1:{port}{request.scope.get('root_path', '')}"


@router.post(
    "/qos/benchmarks",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosBenchmarkStarted,
)
async def start_qos_benchmark(
    request: Request,
    plan: QosBenchmarkRequest,
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> QosBenchmarkStarted:
    from litellm.proxy.proxy_server import llm_router, master_key

    _require_role(user_api_key_dict, (LitellmUserRoles.PROXY_ADMIN,))
    if llm_router is None or plan.model_group not in llm_router.get_model_names():
        raise HTTPException(status_code=404, detail=f"Model {plan.model_group} is not configured on this gateway")
    started_at: Final = _utc_now()
    run_id: Final = new_run_id(plan.model_group, started_at)
    start_benchmark(_loopback_base_url(request), master_key, run_id, plan)
    return QosBenchmarkStarted(
        run_id=run_id,
        model_group=plan.model_group,
        concurrency=plan.concurrency,
        requests_per_worker=plan.requests_per_worker,
        max_tokens=plan.max_tokens,
        total_requests=plan.total_requests,
        started_at=started_at,
    )


@router.get(
    "/qos/benchmarks",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosBenchmarkListResponse,
)
async def list_qos_benchmarks(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    start_time: Annotated[datetime | None, Query(description="ISO 8601, defaults to 7 days before end_time")] = None,
    end_time: Annotated[datetime | None, Query(description="ISO 8601, defaults to now")] = None,
) -> QosBenchmarkListResponse:
    from litellm.proxy.proxy_server import prisma_client

    _require_role(user_api_key_dict, (LitellmUserRoles.PROXY_ADMIN, LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY))
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    start, end = resolve_window(start_time, end_time, _utc_now(), QOS_RUNS_DEFAULT_WINDOW)
    return QosBenchmarkListResponse(
        runs=tuple(_RUNS.validate_python(await prisma_client.db.query_raw(BENCHMARK_RUNS_SQL, start, end)))
    )


@router.get(
    "/qos/benchmarks/{run_id}",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosBenchmarkDetail,
)
async def get_qos_benchmark(
    run_id: str,
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> QosBenchmarkDetail:
    from litellm.proxy.proxy_server import prisma_client

    _require_role(user_api_key_dict, (LitellmUserRoles.PROXY_ADMIN, LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY))
    if _RUN_ID.fullmatch(run_id) is None:
        raise HTTPException(status_code=400, detail="Not a QoS benchmark run id")
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    end: Final = _utc_now() + timedelta(minutes=1)
    start: Final = end - QOS_MAX_WINDOW
    level_rows: Final = _ROWS.validate_python(
        await prisma_client.db.query_raw(BENCHMARK_LEVEL_SUMMARY_SQL, start, end, None, run_id)
    )
    deployment_rows: Final = _ROWS.validate_python(
        await prisma_client.db.query_raw(DEPLOYMENT_SUMMARY_SQL, start, end, None, run_id)
    )
    levels: Final = (
        QosBenchmarkLevel(**group_metrics(row).model_dump(), concurrency=concurrency_of(row.level_tag, run_id))
        for row in level_rows
    )
    return QosBenchmarkDetail(
        run_id=run_id,
        levels=tuple(sorted(levels, key=lambda level: level.concurrency)),
        deployments=tuple(deployment_metrics(row) for row in deployment_rows),
    )
