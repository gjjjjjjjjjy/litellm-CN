import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ConfigDict, TypeAdapter

from litellm.constants import LITTELM_INTERNAL_HEALTH_SERVICE_ACCOUNT_NAME
from litellm.litellm_core_utils.get_llm_provider_logic import get_llm_provider
from litellm.proxy._types import CommonProxyErrors, LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.management_endpoints.qos_benchmark import QOS_RUN_PREFIX, concurrency_of, new_run_id, start_benchmark
from litellm.proxy.management_endpoints.qos_health import (
    HEALTH_HISTORY_ROWS,
    HEALTH_HISTORY_SQL,
    HEALTH_PROBE_ROWS,
    HEALTH_PROBES_SQL,
    DeploymentTarget,
    health_node,
    health_probe,
    probe_key,
)
from litellm.proxy.management_endpoints.qos_response_check import RESPONSE_CHECK_KEY, record_response_checks
from litellm.types.llms.base import LiteLLMBaseModel
from litellm.types.qos import (
    QosBenchmarkDeleted,
    QosBenchmarkDeploymentLevel,
    QosBenchmarkDetail,
    QosBenchmarkLevel,
    QosBenchmarkListResponse,
    QosBenchmarkRequest,
    QosBenchmarkRun,
    QosBenchmarkStarted,
    QosDeploymentMetrics,
    QosHealthResponse,
    QosInterference,
    QosModelGroupMetrics,
    QosPercentiles,
    QosResponseChecks,
    QosSummaryResponse,
    QosTargetDeployment,
    QosTargetModel,
    QosTargetsResponse,
)

if TYPE_CHECKING:
    from litellm.router import Router

router: Final = APIRouter()

QOS_DEFAULT_WINDOW: Final = timedelta(hours=24)
QOS_MAX_WINDOW: Final = timedelta(days=31)
QOS_RUNS_DEFAULT_WINDOW: Final = timedelta(days=7)
RESPONSE_CHECK_RECORD_ATTEMPTS: Final = 30
RESPONSE_CHECK_RETRY_SECONDS: Final = 5.0
_RUN_ID: Final = re.compile(rf"{QOS_RUN_PREFIX}[A-Za-z0-9.-]+")

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


def _logged_model_group(deployment_groups_param: str) -> str:
    """A request that addressed a deployment by id is logged with the id as its model group; report its model name."""
    return (
        f"CASE WHEN {deployment_groups_param}::jsonb ? model_group "
        f"THEN {deployment_groups_param}::jsonb ->> model_group ELSE COALESCE(model_group, '') END"
    )


BENCHMARK_RUNS_SQL: Final = f"""
SELECT
    run_tag AS run_id,
    MAX({_logged_model_group("$3")}) AS model_group,
    COUNT(*)::int AS requests,
    (COUNT(*) FILTER (WHERE status = 'failure'))::int AS failed_requests,
    (COUNT(*) FILTER (WHERE metadata->>'{RESPONSE_CHECK_KEY}' = 'crosstalk'))::int AS crosstalk_responses,
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
        status,
        "startTime" AS started,
        "endTime" AS ended,
        completion_tokens,
        metadata->>'{response_check_key}' AS response_check,
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
        AND COALESCE(model, '') <> ''
        AND ($3::text IS NULL OR {model_group} = $3::text)
        AND {tag_filter}
        AND {health_check_filter}
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
_EXCLUDE_HEALTH_CHECKS: Final = f"NOT COALESCE(request_tags ? '{LITTELM_INTERNAL_HEALTH_SERVICE_ACCOUNT_NAME}', false)"
_REQUEST_TAG_FILTER: Final = "($4::text IS NULL OR request_tags ? $4::text)"
_SUMMARY_MODEL_GROUP: Final = _logged_model_group("$5")
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
    model_group=_SUMMARY_MODEL_GROUP,
    response_check_key=RESPONSE_CHECK_KEY,
    source=_SPEND_LOGS,
    tag_filter=_REQUEST_TAG_FILTER,
    health_check_filter=_EXCLUDE_HEALTH_CHECKS,
)
MODEL_GROUP_SUMMARY_SQL: Final = _SUMMARY_SQL.format(
    keys="model_group",
    selected_keys="base.model_group",
    level_column="",
    model_group=_SUMMARY_MODEL_GROUP,
    response_check_key=RESPONSE_CHECK_KEY,
    source=_SPEND_LOGS,
    tag_filter=_REQUEST_TAG_FILTER,
    health_check_filter=_EXCLUDE_HEALTH_CHECKS,
)
BENCHMARK_LEVEL_SUMMARY_SQL: Final = _SUMMARY_SQL.format(
    keys="model_group, level_tag",
    selected_keys="base.model_group, base.level_tag",
    level_column=",\n        level_tag",
    model_group=_SUMMARY_MODEL_GROUP,
    response_check_key=RESPONSE_CHECK_KEY,
    source=_LEVEL_SOURCE,
    tag_filter=_LEVEL_TAG_FILTER,
    health_check_filter=_EXCLUDE_HEALTH_CHECKS,
)
BENCHMARK_DEPLOYMENT_LEVEL_SUMMARY_SQL: Final = _SUMMARY_SQL.format(
    keys="model_group, model_id, level_tag",
    selected_keys="base.model_group, base.model_id, base.level_tag",
    level_column=",\n        level_tag",
    model_group=_SUMMARY_MODEL_GROUP,
    response_check_key=RESPONSE_CHECK_KEY,
    source=_LEVEL_SOURCE,
    tag_filter=_LEVEL_TAG_FILTER,
    health_check_filter=_EXCLUDE_HEALTH_CHECKS,
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


_ROWS: Final = TypeAdapter(list[QosSummaryRow])
_INTERFERENCE_ROWS: Final = TypeAdapter(list[InterferenceRow])
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


def deployment_model_groups(llm_router: "Router | None") -> str:
    if llm_router is None:
        return "{}"
    return json.dumps(
        {
            model_id: deployment.model_name
            for model_id in llm_router.get_model_ids()
            if (deployment := llm_router.get_deployment(model_id)) is not None
        }
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
    from litellm.proxy.proxy_server import llm_router, prisma_client

    if user_api_key_dict.user_role not in (LitellmUserRoles.PROXY_ADMIN, LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY):
        raise HTTPException(status_code=403, detail="Only proxy admins can view service quality metrics")
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)

    start, end = resolve_window(start_time, end_time, datetime.now(timezone.utc).replace(tzinfo=None))
    groups: Final = deployment_model_groups(llm_router)
    group_rows: Final = _ROWS.validate_python(
        await prisma_client.db.query_raw(MODEL_GROUP_SUMMARY_SQL, start, end, model_group, tag, groups)
    )
    deployment_rows: Final = _ROWS.validate_python(
        await prisma_client.db.query_raw(DEPLOYMENT_SUMMARY_SQL, start, end, model_group, tag, groups)
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
    from litellm.proxy.proxy_server import llm_router, master_key, prisma_client

    _require_role(user_api_key_dict, (LitellmUserRoles.PROXY_ADMIN,))
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    if llm_router is None or plan.model_group not in llm_router.get_model_names():
        raise HTTPException(status_code=404, detail=f"Model {plan.model_group} is not configured on this gateway")
    unknown_deployments: Final = set(plan.deployment_ids) - set(llm_router.get_model_ids(model_name=plan.model_group))
    if unknown_deployments:
        raise HTTPException(
            status_code=400,
            detail=f"Not deployments of {plan.model_group}: {', '.join(sorted(unknown_deployments))}",
        )
    started_at: Final = _utc_now()
    run_id: Final = new_run_id(plan.model_group, started_at)
    record_checks: Final = partial(
        record_response_checks,
        prisma_client,
        since=started_at,
        attempts=RESPONSE_CHECK_RECORD_ATTEMPTS,
        retry_seconds=RESPONSE_CHECK_RETRY_SECONDS,
    )
    start_benchmark(_loopback_base_url(request), master_key, run_id, plan, record_checks)
    return QosBenchmarkStarted(
        run_id=run_id,
        model_group=plan.model_group,
        deployment_ids=plan.deployment_ids,
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
    from litellm.proxy.proxy_server import llm_router, prisma_client

    _require_role(user_api_key_dict, (LitellmUserRoles.PROXY_ADMIN, LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY))
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    start, end = resolve_window(start_time, end_time, _utc_now(), QOS_RUNS_DEFAULT_WINDOW)
    rows: Final = await prisma_client.db.query_raw(BENCHMARK_RUNS_SQL, start, end, deployment_model_groups(llm_router))
    return QosBenchmarkListResponse(runs=tuple(_RUNS.validate_python(rows)))


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
    from litellm.proxy.proxy_server import llm_router, prisma_client

    _require_role(user_api_key_dict, (LitellmUserRoles.PROXY_ADMIN, LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY))
    if _RUN_ID.fullmatch(run_id) is None:
        raise HTTPException(status_code=400, detail="Not a QoS benchmark run id")
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    end: Final = _utc_now() + timedelta(minutes=1)
    start: Final = end - QOS_MAX_WINDOW
    groups: Final = deployment_model_groups(llm_router)
    level_rows: Final = _ROWS.validate_python(
        await prisma_client.db.query_raw(BENCHMARK_LEVEL_SUMMARY_SQL, start, end, None, run_id, groups)
    )
    deployment_rows: Final = _ROWS.validate_python(
        await prisma_client.db.query_raw(DEPLOYMENT_SUMMARY_SQL, start, end, None, run_id, groups)
    )
    deployment_level_rows: Final = _ROWS.validate_python(
        await prisma_client.db.query_raw(BENCHMARK_DEPLOYMENT_LEVEL_SUMMARY_SQL, start, end, None, run_id, groups)
    )
    interference_rows: Final = _INTERFERENCE_ROWS.validate_python(
        await prisma_client.db.query_raw(BENCHMARK_INTERFERENCE_SQL, start, end, run_id)
    )
    interference: Final = {(row.model_id, row.level_tag): row for row in interference_rows}
    levels: Final = (
        QosBenchmarkLevel(
            **group_metrics(row).model_dump(),
            concurrency=concurrency_of(row.level_tag, run_id),
            interference=level_interference(row.level_tag, interference_rows),
        )
        for row in level_rows
    )
    deployment_levels: Final = (
        QosBenchmarkDeploymentLevel(
            **deployment_metrics(row).model_dump(),
            concurrency=concurrency_of(row.level_tag, run_id),
            interference=deployment_interference(interference[(row.model_id, row.level_tag)]),
        )
        for row in deployment_level_rows
    )
    return QosBenchmarkDetail(
        run_id=run_id,
        levels=tuple(sorted(levels, key=lambda level: level.concurrency)),
        deployments=tuple(deployment_metrics(row) for row in deployment_rows),
        deployment_levels=tuple(sorted(deployment_levels, key=lambda level: (level.concurrency, level.model_id))),
    )


def deployment_target_lookup(llm_router: "Router | None") -> Callable[[str], DeploymentTarget | None]:
    def target_of(model_id: str) -> DeploymentTarget | None:
        deployment: Final = None if llm_router is None else llm_router.get_deployment(model_id)
        if deployment is None:
            return None
        params: Final = deployment.litellm_params
        upstream_model, provider, _, default_api_base = get_llm_provider(
            model=params.model, custom_llm_provider=params.custom_llm_provider
        )
        if params.api_base is not None:
            return DeploymentTarget(provider=provider, api_base=params.api_base, upstream_model=upstream_model)
        return DeploymentTarget(
            provider=provider,
            api_base=provider if default_api_base is None else default_api_base,
            upstream_model=upstream_model,
        )

    return target_of


def target_deployment(model_id: str, target: DeploymentTarget) -> QosTargetDeployment:
    return QosTargetDeployment(
        model_id=model_id, provider=target.provider, api_base=target.api_base, upstream_model=target.upstream_model
    )


@router.get(
    "/qos/targets",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosTargetsResponse,
)
async def get_qos_targets(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> QosTargetsResponse:
    """Every model name with the provider deployments behind it, so a benchmark can target one or compare them."""
    from litellm.proxy.proxy_server import llm_router

    _require_role(user_api_key_dict, (LitellmUserRoles.PROXY_ADMIN, LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY))
    if llm_router is None:
        return QosTargetsResponse(models=())
    target_of: Final = deployment_target_lookup(llm_router)
    return QosTargetsResponse(
        models=tuple(
            QosTargetModel(
                model_group=model_group,
                deployments=tuple(
                    target_deployment(model_id, target)
                    for model_id in llm_router.get_model_ids(model_name=model_group)
                    if (target := target_of(model_id)) is not None
                ),
            )
            for model_group in sorted(set(llm_router.get_model_names()))
        )
    )


@router.get(
    "/qos/health",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosHealthResponse,
)
async def get_qos_health(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    start_time: Annotated[datetime | None, Query(description="ISO 8601, defaults to 24 hours before end_time")] = None,
    end_time: Annotated[datetime | None, Query(description="ISO 8601, defaults to now")] = None,
) -> QosHealthResponse:
    from litellm.proxy.proxy_server import llm_router, prisma_client

    _require_role(user_api_key_dict, (LitellmUserRoles.PROXY_ADMIN, LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY))
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    start, end = resolve_window(start_time, end_time, _utc_now())
    history: Final = HEALTH_HISTORY_ROWS.validate_python(
        await prisma_client.db.query_raw(HEALTH_HISTORY_SQL, start, end)
    )
    probes: Final = HEALTH_PROBE_ROWS.validate_python(await prisma_client.db.query_raw(HEALTH_PROBES_SQL, start, end))
    target_of: Final = deployment_target_lookup(llm_router)
    model_ids: Final = () if llm_router is None else tuple(llm_router.get_model_ids())
    current_probe_keys: Final = frozenset(
        probe_key(target.api_base, target.upstream_model) for target in map(target_of, model_ids) if target is not None
    )
    return QosHealthResponse(
        start_time=start,
        end_time=end,
        nodes=tuple(health_node(row, target) for row in history if (target := target_of(row.model_id)) is not None),
        probes=tuple(health_probe(row) for row in probes if probe_key(row.api_base, row.model) in current_probe_keys),
    )


class _DeletedCount(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    deleted_requests: int


_DELETED_COUNT: Final = TypeAdapter(list[_DeletedCount])


@router.delete(
    "/qos/benchmarks/{run_id}",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosBenchmarkDeleted,
)
async def delete_qos_benchmark(
    run_id: str,
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> QosBenchmarkDeleted:
    from litellm.proxy.proxy_server import prisma_client

    _require_role(user_api_key_dict, (LitellmUserRoles.PROXY_ADMIN,))
    if _RUN_ID.fullmatch(run_id) is None:
        raise HTTPException(status_code=400, detail="Not a QoS benchmark run id")
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    since: Final = _utc_now() - QOS_MAX_WINDOW
    (result,) = _DELETED_COUNT.validate_python(await prisma_client.db.query_raw(BENCHMARK_DELETE_SQL, since, run_id))
    return QosBenchmarkDeleted(run_id=run_id, deleted_requests=result.deleted_requests)
