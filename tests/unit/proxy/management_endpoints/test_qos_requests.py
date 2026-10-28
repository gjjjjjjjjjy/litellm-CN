from datetime import datetime, timezone
from typing import Final

from litellm.proxy.management_endpoints.qos_requests import RequestRow, request_log
from litellm.types.qos import QosBenchmarkExchange


def test_saved_text_is_kept_exactly_and_provider_aliases_are_resolved() -> None:
    exchange: Final = QosBenchmarkExchange(
        question="Question\nQOS-0123456789AB", answer="<b>答案</b>", reasoning="think", error=None
    )
    row: Final = RequestRow(
        request_id="request-1",
        started_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
        concurrency=32,
        model_id="node-1",
        api_base="https://ai.gitee.com/v1",
        custom_llm_provider="openai",
        status="success",
        response_check="passed",
        exchange=exchange,
    )

    result: Final = request_log(row)

    assert result.exchange == exchange
    assert (result.vendor, result.api_base, result.concurrency) == ("moark", row.api_base, 32)


def test_old_logs_keep_their_missing_exchange_explicit() -> None:
    row: Final = RequestRow(
        request_id="old-request",
        started_at=datetime(2026, 10, 28),
        concurrency=None,
        model_id="node-1",
        api_base="",
        custom_llm_provider="moark",
        status=None,
        response_check=None,
        exchange=None,
    )
    result: Final = request_log(row)
    assert (result.exchange, result.response_check, result.concurrency, result.status) == (None, None, None, None)
