from datetime import datetime, timedelta
from typing import Final

import pytest

from litellm.proxy.management_endpoints.qos_trends import (
    TREND_POINTS,
    OverallRow,
    TrendRow,
    bucket_seconds,
    overall,
    trend_series,
)


def _trend_row(model_group: str, model_id: str, hour: int, **overrides: object) -> TrendRow:
    return TrendRow.model_validate(
        {
            "model_group": model_group,
            "model_id": model_id,
            "bucket_start": datetime(2026, 10, 26, hour),
            "api_base": "https://ai.gitee.com/v1",
            "custom_llm_provider": "openai",
            "requests": 10,
            "failed_requests": 1,
            "output_tokens": 1000,
            "ttft_p50": 300.0,
            "ttft_p95": 900.0,
            "ttft_p99": 1200.0,
            "tpot_p50": 20.0,
            "tpot_p95": 40.0,
            "tpot_p99": 60.0,
            **overrides,
        }
    )


@pytest.mark.parametrize(
    ("window", "expected"),
    [
        (timedelta(minutes=15), 60),
        (timedelta(hours=1), 60),
        (timedelta(hours=6), 600),
        (timedelta(hours=24), 1800),
        (timedelta(days=7), 14400),
        (timedelta(days=31), 86400),
    ],
)
def test_buckets_keep_each_series_within_the_point_budget(window: timedelta, expected: int) -> None:
    assert bucket_seconds(window) == expected
    assert window.total_seconds() / expected <= TREND_POINTS


def test_each_series_collects_its_own_buckets_in_order() -> None:
    rows: Final = [
        _trend_row("GLM-5.3", "", 1),
        _trend_row("GLM-5.3", "", 2, requests=7),
        _trend_row("Qwen3", "", 1, requests=3),
    ]

    series: Final = trend_series(rows)

    assert [(item.model_group, [point.requests for point in item.points]) for item in series] == [
        ("GLM-5.3", [10, 7]),
        ("Qwen3", [3]),
    ]
    assert (series[0].vendor, series[0].api_base) == ("", "")
    assert series[0].points[0].ttft_ms.p95 == 900.0


@pytest.mark.parametrize("days", (61, 365, 730, 3650))
def test_long_history_keeps_the_same_point_budget(days: int) -> None:
    window: Final = timedelta(days=days)
    assert window.total_seconds() / bucket_seconds(window) <= TREND_POINTS


def test_a_deployment_series_names_its_vendor() -> None:
    rows: Final = [
        _trend_row("GLM-5.3", "node-gitee", 1),
        _trend_row("GLM-5.3", "node-moark", 1, api_base="https://api.moark.com/v1", custom_llm_provider="moark"),
    ]

    assert [(item.model_id, item.vendor, item.api_base) for item in trend_series(rows)] == [
        ("node-gitee", "moark", "https://ai.gitee.com/v1"),
        ("node-moark", "moark", "https://api.moark.com/v1"),
    ]


def test_throughput_spreads_output_over_the_whole_window() -> None:
    row: Final = OverallRow.model_validate(
        {
            "requests": 120,
            "failed_requests": 6,
            "output_tokens": 36000,
            "checked_responses": 100,
            "crosstalk_responses": 2,
            "marker_missing_responses": 1,
            "ttft_p50": 300.0,
            "ttft_p95": 900.0,
            "ttft_p99": None,
            "tpot_p50": None,
            "tpot_p95": None,
            "tpot_p99": None,
        }
    )

    result: Final = overall(row, timedelta(hours=1))

    assert result.output_tokens_per_second == pytest.approx(36000 / 3600)
    assert result.response_checks.crosstalk == 2
    assert (result.ttft_ms.p95, result.tpot_ms.p50) == (900.0, None)
