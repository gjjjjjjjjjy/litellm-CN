"""
Service quality trends for the QoS dashboard: overall figures for a window and for the window just before it,
and per-model or per-deployment time series bucketed so that each series has about TREND_POINTS points.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from itertools import groupby
from math import ceil
from types import MappingProxyType
from typing import Final, Literal, TypeAlias

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
from litellm.types.qos import QosOverall, QosPercentiles, QosResponseChecks, QosTrendPoint, QosTrendSeries

TrendGrouping: TypeAlias = Literal["model", "deployment"]

TREND_POINTS: Final = 60
TREND_BUCKET_SECONDS: Final = (60, 120, 300, 600, 900, 1800, 3600, 7200, 14400, 21600, 43200, 86400)

_PERCENTILES: Final = """
    percentile_cont(0.5) WITHIN GROUP (ORDER BY ttft_ms) AS ttft_p50,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY ttft_ms) AS ttft_p95,
    percentile_cont(0.99) WITHIN GROUP (ORDER BY ttft_ms) AS ttft_p99,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY tpot_ms) AS tpot_p50,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY tpot_ms) AS tpot_p95,
    percentile_cont(0.99) WITHIN GROUP (ORDER BY tpot_ms) AS tpot_p99"""

_COUNTS: Final = """
    COUNT(*)::int AS requests,
    (COUNT(*) FILTER (WHERE status = 'failure'))::int AS failed_requests,
    COALESCE(SUM(completion_tokens) FILTER (WHERE status IS DISTINCT FROM 'failure'), 0)::int AS output_tokens"""

OVERALL_SQL: Final = f"""
WITH base AS (
    SELECT
        status,
        completion_tokens,
        {RESPONSE_CHECK} AS response_check,
        {TTFT_MS} AS ttft_ms,
        {TPOT_MS} AS tpot_ms
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= $1::timestamp
        AND "startTime" < $2::timestamp
        AND {MODEL_TRAFFIC}
        AND ($3::text IS NULL OR request_tags ? $3::text)
)
SELECT
    {_COUNTS},
    COUNT(response_check)::int AS checked_responses,
    (COUNT(*) FILTER (WHERE response_check = 'crosstalk'))::int AS crosstalk_responses,
    (COUNT(*) FILTER (WHERE response_check = 'marker_missing'))::int AS marker_missing_responses,
    {_PERCENTILES}
FROM base
"""

_TREND_SQL: Final = """
WITH base AS (
    SELECT
        {model_group} AS model_group,
        {model_id} AS model_id,
        COALESCE(api_base, '') AS api_base,
        COALESCE(custom_llm_provider, '') AS custom_llm_provider,
        to_timestamp(floor(EXTRACT(epoch FROM "startTime") / $3::int) * $3::int) AT TIME ZONE 'UTC' AS bucket_start,
        status,
        completion_tokens,
        {ttft_ms} AS ttft_ms,
        {tpot_ms} AS tpot_ms
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= $1::timestamp
        AND "startTime" < $2::timestamp
        AND {model_traffic}
        AND ($4::text IS NULL OR request_tags ? $4::text)
)
SELECT
    model_group,
    model_id,
    bucket_start,
    MAX(api_base) AS api_base,
    MAX(custom_llm_provider) AS custom_llm_provider,
    {counts},
    {percentiles}
FROM base
GROUP BY model_group, model_id, bucket_start
ORDER BY model_group, model_id, bucket_start
"""

TREND_SQL: Final = MappingProxyType(
    {
        grouping: _TREND_SQL.format(
            model_group=logged_model_group("$5"),
            model_id=model_id,
            ttft_ms=TTFT_MS,
            tpot_ms=TPOT_MS,
            model_traffic=MODEL_TRAFFIC,
            counts=_COUNTS,
            percentiles=_PERCENTILES,
        )
        for grouping, model_id in (("model", "''"), ("deployment", "COALESCE(model_id, '')"))
    }
)


class _Latencies(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    ttft_p50: float | None
    ttft_p95: float | None
    ttft_p99: float | None
    tpot_p50: float | None
    tpot_p95: float | None
    tpot_p99: float | None

    def ttft(self) -> QosPercentiles:
        return QosPercentiles(p50=self.ttft_p50, p95=self.ttft_p95, p99=self.ttft_p99)

    def tpot(self) -> QosPercentiles:
        return QosPercentiles(p50=self.tpot_p50, p95=self.tpot_p95, p99=self.tpot_p99)


class OverallRow(_Latencies):
    requests: int
    failed_requests: int
    output_tokens: int
    checked_responses: int
    crosstalk_responses: int
    marker_missing_responses: int


class TrendRow(_Latencies):
    model_group: str
    model_id: str
    bucket_start: datetime
    api_base: str
    custom_llm_provider: str
    requests: int
    failed_requests: int
    output_tokens: int


OVERALL_ROWS: Final = TypeAdapter(tuple[OverallRow])
TREND_ROWS: Final = TypeAdapter(list[TrendRow])

EMPTY_HISTORY_OVERALL: Final = QosOverall(
    requests=0,
    failed_requests=0,
    output_tokens=0,
    output_tokens_per_second=None,
    ttft_ms=QosPercentiles(p50=None, p95=None, p99=None),
    tpot_ms=QosPercentiles(p50=None, p95=None, p99=None),
    response_checks=QosResponseChecks(checked=0, crosstalk=0, marker_missing=0),
)


def bucket_seconds(window: timedelta) -> int:
    """The shortest bucket that keeps a series within TREND_POINTS points."""
    return next(
        (seconds for seconds in TREND_BUCKET_SECONDS if window.total_seconds() / seconds <= TREND_POINTS),
        max(1, ceil(window.total_seconds() / TREND_POINTS / 86400)) * 86400,
    )


def overall(row: OverallRow, window: timedelta) -> QosOverall:
    return QosOverall(
        requests=row.requests,
        failed_requests=row.failed_requests,
        output_tokens=row.output_tokens,
        output_tokens_per_second=row.output_tokens / window.total_seconds(),
        ttft_ms=row.ttft(),
        tpot_ms=row.tpot(),
        response_checks=QosResponseChecks(
            checked=row.checked_responses,
            crosstalk=row.crosstalk_responses,
            marker_missing=row.marker_missing_responses,
        ),
    )


def _point(row: TrendRow) -> QosTrendPoint:
    return QosTrendPoint(
        bucket_start=row.bucket_start,
        requests=row.requests,
        failed_requests=row.failed_requests,
        output_tokens=row.output_tokens,
        ttft_ms=row.ttft(),
        tpot_ms=row.tpot(),
    )


def _series(rows: Sequence[TrendRow]) -> QosTrendSeries:
    first: Final = rows[0]
    return QosTrendSeries(
        model_group=first.model_group,
        model_id=first.model_id,
        vendor="" if first.model_id == "" else vendor_of(first.custom_llm_provider, first.api_base),
        api_base="" if first.model_id == "" else first.api_base,
        points=tuple(_point(row) for row in rows),
    )


def trend_series(rows: Sequence[TrendRow]) -> tuple[QosTrendSeries, ...]:
    """Rows arrive ordered by series and bucket; each run of one series becomes its time series."""
    return tuple(
        _series(tuple(series_rows)) for _, series_rows in groupby(rows, key=lambda row: (row.model_group, row.model_id))
    )
