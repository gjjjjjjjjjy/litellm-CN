from datetime import datetime
from typing import Final, Literal

from pydantic import ConfigDict, TypeAdapter

from litellm.proxy.management_endpoints.qos_health import vendor_of
from litellm.proxy.management_endpoints.qos_response_check import BENCHMARK_EXCHANGE_KEY, RESPONSE_CHECK_KEY
from litellm.types.llms.base import LiteLLMBaseModel
from litellm.types.qos import QosBenchmarkExchange, QosBenchmarkRequestLog

REQUESTS_SQL: Final = f"""
SELECT request_id, "startTime" AS started_at,
    (SELECT substring(tag FROM length($2::text) + 3)::int
        FROM jsonb_array_elements_text(request_tags) AS tag
        WHERE left(tag, length($2::text) + 2) = $2::text || '@c'
            AND substring(tag FROM length($2::text) + 3) ~ '^[0-9]+$'
        LIMIT 1) AS concurrency,
    COALESCE(model_id, '') AS model_id,
    COALESCE(api_base, '') AS api_base,
    COALESCE(custom_llm_provider, '') AS custom_llm_provider,
    status, metadata->>'{RESPONSE_CHECK_KEY}' AS response_check,
    metadata->'{BENCHMARK_EXCHANGE_KEY}' AS exchange
FROM "LiteLLM_SpendLogs"
WHERE "startTime" >= $1::timestamp AND request_tags ? $2::text
ORDER BY "startTime", request_id
LIMIT $3::int OFFSET $4::int
"""

REQUEST_COUNT_SQL: Final = """
SELECT COUNT(*)::int AS total FROM "LiteLLM_SpendLogs"
WHERE "startTime" >= $1::timestamp AND request_tags ? $2::text
"""


class RequestRow(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    started_at: datetime
    concurrency: int | None
    model_id: str
    api_base: str
    custom_llm_provider: str
    status: str | None
    response_check: Literal["passed", "crosstalk", "marker_missing"] | None
    exchange: QosBenchmarkExchange | None


class RequestCount(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    total: int


REQUEST_ROWS: Final = TypeAdapter(tuple[RequestRow, ...])
REQUEST_COUNT_ROWS: Final = TypeAdapter(tuple[RequestCount])


def request_log(row: RequestRow) -> QosBenchmarkRequestLog:
    return QosBenchmarkRequestLog(
        request_id=row.request_id,
        started_at=row.started_at,
        concurrency=row.concurrency,
        model_id=row.model_id,
        api_base=row.api_base,
        vendor=vendor_of(row.custom_llm_provider, row.api_base),
        status=row.status,
        response_check=row.response_check,
        exchange=row.exchange,
    )
