import re
from datetime import datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ConfigDict, TypeAdapter

from litellm.proxy._types import CommonProxyErrors, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.management_endpoints.qos_access import require_admin, require_content_reader, require_reader
from litellm.proxy.management_endpoints.qos_benchmark import QOS_RUN_PREFIX, concurrency_of, new_run_id, start_benchmark
from litellm.proxy.management_endpoints.qos_deployments import (
    deployment_model_groups,
    deployment_target_lookup,
    target_deployment,
)
from litellm.proxy.management_endpoints.qos_health import (
    HEALTH_HISTORY_ROWS,
    HEALTH_HISTORY_SQL,
    HEALTH_PROBE_ROWS,
    HEALTH_PROBES_SQL,
    health_node,
    health_probe,
    probe_key,
)
from litellm.proxy.management_endpoints.qos_requests import (
    REQUEST_COUNT_ROWS,
    REQUEST_COUNT_SQL,
    REQUEST_ROWS,
    REQUESTS_SQL,
    request_log,
)
from litellm.proxy.management_endpoints.qos_response_check import ResponseCheckRecorder, write_response_checks
from litellm.proxy.management_endpoints.qos_summary import (
    BENCHMARK_DELETE_SQL,
    BENCHMARK_DEPLOYMENT_LEVEL_SUMMARY_SQL,
    BENCHMARK_INTERFERENCE_SQL,
    BENCHMARK_LEVEL_SUMMARY_SQL,
    BENCHMARK_RUNS,
    BENCHMARK_RUNS_SQL,
    DEPLOYMENT_SUMMARY_SQL,
    HISTORY_START_ROWS,
    HISTORY_START_SQL,
    INTERFERENCE_ROWS,
    MODEL_GROUP_SUMMARY_SQL,
    QOS_MAX_WINDOW,
    QOS_RUNS_DEFAULT_WINDOW,
    SUMMARY_ROWS,
    as_utc_naive,
    deployment_interference,
    deployment_metrics,
    group_metrics,
    level_interference,
    resolve_window,
    utc_now,
)
from litellm.proxy.management_endpoints.qos_trends import (
    EMPTY_HISTORY_OVERALL,
    OVERALL_ROWS,
    OVERALL_SQL,
    TREND_ROWS,
    TREND_SQL,
    TrendGrouping,
    bucket_seconds,
    overall,
    trend_series,
)
from litellm.types.llms.base import LiteLLMBaseModel
from litellm.types.qos import (
    QosBenchmarkDeleted,
    QosBenchmarkDeploymentLevel,
    QosBenchmarkDetail,
    QosBenchmarkLevel,
    QosBenchmarkListResponse,
    QosBenchmarkRequest,
    QosBenchmarkRequests,
    QosBenchmarkStarted,
    QosHealthResponse,
    QosSummaryResponse,
    QosTargetModel,
    QosTargetsResponse,
    QosTrendsResponse,
)

if TYPE_CHECKING:
    from litellm.proxy.utils import PrismaClient

router: Final = APIRouter()

RESPONSE_CHECK_RECORD_ATTEMPTS: Final = 30
RESPONSE_CHECK_RETRY_SECONDS: Final = 5.0
_RUN_ID: Final = re.compile(rf"{QOS_RUN_PREFIX}[A-Za-z0-9.-]+")


async def _metrics_window(
    prisma_client: "PrismaClient",
    start_time: datetime | None,
    end_time: datetime | None,
    all_time: bool,
) -> tuple[datetime, datetime]:
    now: Final = utc_now()
    if not all_time:
        return resolve_window(start_time, end_time, now)
    if start_time is not None:
        raise HTTPException(status_code=400, detail="all_time and start_time cannot be combined")
    end: Final = as_utc_naive(now if end_time is None else end_time)
    (history,) = HISTORY_START_ROWS.validate_python(await prisma_client.db.query_raw(HISTORY_START_SQL, end))
    return (end if history.start_time is None else as_utc_naive(history.start_time)), end


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
    all_time: Annotated[
        bool, Query(description="Include all retained history; cannot be combined with start_time")
    ] = False,
) -> QosSummaryResponse:
    from litellm.proxy.proxy_server import llm_router, prisma_client

    require_reader(user_api_key_dict)
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)

    start, end = await _metrics_window(prisma_client, start_time, end_time, all_time)
    groups: Final = deployment_model_groups(llm_router)
    group_rows: Final = SUMMARY_ROWS.validate_python(
        await prisma_client.db.query_raw(MODEL_GROUP_SUMMARY_SQL, start, end, model_group, tag, groups)
    )
    deployment_rows: Final = SUMMARY_ROWS.validate_python(
        await prisma_client.db.query_raw(DEPLOYMENT_SUMMARY_SQL, start, end, model_group, tag, groups)
    )
    return QosSummaryResponse(
        start_time=start,
        end_time=end,
        tag=tag,
        model_groups=tuple(group_metrics(row) for row in group_rows),
        deployments=tuple(deployment_metrics(row) for row in deployment_rows),
    )


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

    require_admin(user_api_key_dict)
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
    started_at: Final = utc_now()
    run_id: Final = new_run_id(plan.model_group, started_at)
    recorder: Final = ResponseCheckRecorder(
        write=partial(write_response_checks, prisma_client, started_at),
        attempts=RESPONSE_CHECK_RECORD_ATTEMPTS,
        retry_seconds=RESPONSE_CHECK_RETRY_SECONDS,
    )
    start_benchmark(_loopback_base_url(request), master_key, run_id, plan, recorder)
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

    require_reader(user_api_key_dict)
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    start, end = resolve_window(start_time, end_time, utc_now(), QOS_RUNS_DEFAULT_WINDOW)
    runs: Final = BENCHMARK_RUNS.validate_python(
        await prisma_client.db.query_raw(BENCHMARK_RUNS_SQL, start, end, deployment_model_groups(llm_router))
    )
    return QosBenchmarkListResponse(runs=tuple(runs))


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

    require_reader(user_api_key_dict)
    if _RUN_ID.fullmatch(run_id) is None:
        raise HTTPException(status_code=400, detail="Not a QoS benchmark run id")
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    end: Final = utc_now() + timedelta(minutes=1)
    start: Final = end - QOS_MAX_WINDOW
    groups: Final = deployment_model_groups(llm_router)
    level_rows: Final = SUMMARY_ROWS.validate_python(
        await prisma_client.db.query_raw(BENCHMARK_LEVEL_SUMMARY_SQL, start, end, None, run_id, groups)
    )
    deployment_rows: Final = SUMMARY_ROWS.validate_python(
        await prisma_client.db.query_raw(DEPLOYMENT_SUMMARY_SQL, start, end, None, run_id, groups)
    )
    deployment_level_rows: Final = SUMMARY_ROWS.validate_python(
        await prisma_client.db.query_raw(BENCHMARK_DEPLOYMENT_LEVEL_SUMMARY_SQL, start, end, None, run_id, groups)
    )
    interference_rows: Final = INTERFERENCE_ROWS.validate_python(
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


@router.get(
    "/qos/benchmarks/{run_id}/requests",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosBenchmarkRequests,
)
async def get_qos_benchmark_requests(
    run_id: str,
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 10,
) -> QosBenchmarkRequests:
    from litellm.proxy.proxy_server import prisma_client

    require_content_reader(user_api_key_dict)
    if _RUN_ID.fullmatch(run_id) is None:
        raise HTTPException(status_code=400, detail="Not a QoS benchmark run id")
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    since: Final = utc_now() - QOS_MAX_WINDOW
    (count,) = REQUEST_COUNT_ROWS.validate_python(await prisma_client.db.query_raw(REQUEST_COUNT_SQL, since, run_id))
    rows: Final = REQUEST_ROWS.validate_python(
        await prisma_client.db.query_raw(REQUESTS_SQL, since, run_id, page_size, (page - 1) * page_size)
    )
    return QosBenchmarkRequests(
        requests=tuple(request_log(row) for row in rows), total=count.total, page=page, page_size=page_size
    )


@router.get(
    "/qos/trends",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosTrendsResponse,
)
async def get_qos_trends(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    start_time: Annotated[datetime | None, Query(description="ISO 8601, defaults to 24 hours before end_time")] = None,
    end_time: Annotated[datetime | None, Query(description="ISO 8601, defaults to now")] = None,
    tag: Annotated[str | None, Query(description="Only include requests carrying this request tag")] = None,
    group_by: Annotated[
        TrendGrouping, Query(description="One series per model, or per deployment of a model")
    ] = "model",
    all_time: Annotated[
        bool, Query(description="Include all retained history; cannot be combined with start_time")
    ] = False,
) -> QosTrendsResponse:
    """Headline figures for a window and the window before it, and per-model or per-deployment time series."""
    from litellm.proxy.proxy_server import llm_router, prisma_client

    require_reader(user_api_key_dict)
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    start, end = await _metrics_window(prisma_client, start_time, end_time, all_time)
    window: Final = end - start
    bucket: Final = bucket_seconds(window)
    if all_time and start == end:
        return QosTrendsResponse(
            start_time=start,
            end_time=end,
            bucket_seconds=bucket,
            group_by=group_by,
            current=EMPTY_HISTORY_OVERALL,
            previous=EMPTY_HISTORY_OVERALL,
            series=(),
        )
    (current,) = OVERALL_ROWS.validate_python(await prisma_client.db.query_raw(OVERALL_SQL, start, end, tag))
    previous: Final = (
        EMPTY_HISTORY_OVERALL
        if all_time
        else overall(
            OVERALL_ROWS.validate_python(await prisma_client.db.query_raw(OVERALL_SQL, start - window, start, tag))[0],
            window,
        )
    )
    rows: Final = TREND_ROWS.validate_python(
        await prisma_client.db.query_raw(
            TREND_SQL[group_by], start, end, bucket, tag, deployment_model_groups(llm_router)
        )
    )
    return QosTrendsResponse(
        start_time=start,
        end_time=end,
        bucket_seconds=bucket,
        group_by=group_by,
        current=overall(current, window),
        previous=previous,
        series=trend_series(rows),
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

    require_reader(user_api_key_dict)
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
    all_time: Annotated[
        bool, Query(description="Include all retained history; cannot be combined with start_time")
    ] = False,
) -> QosHealthResponse:
    from litellm.proxy.proxy_server import llm_router, prisma_client

    require_reader(user_api_key_dict)
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    start, end = await _metrics_window(prisma_client, start_time, end_time, all_time)
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

    require_admin(user_api_key_dict)
    if _RUN_ID.fullmatch(run_id) is None:
        raise HTTPException(status_code=400, detail="Not a QoS benchmark run id")
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    since: Final = utc_now() - QOS_MAX_WINDOW
    (result,) = _DELETED_COUNT.validate_python(await prisma_client.db.query_raw(BENCHMARK_DELETE_SQL, since, run_id))
    return QosBenchmarkDeleted(run_id=run_id, deleted_requests=result.deleted_requests)
