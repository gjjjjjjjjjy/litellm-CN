from datetime import datetime, timedelta, timezone
from typing import Final
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.management_endpoints.qos_endpoints import (
    BENCHMARK_LEVEL_SUMMARY_SQL,
    DEPLOYMENT_SUMMARY_SQL,
    MODEL_GROUP_SUMMARY_SQL,
    QOS_DEFAULT_WINDOW,
    QOS_MAX_WINDOW,
    resolve_window,
    router,
)

NOW: Final = datetime(2026, 10, 22, 12, 0, 0)


def _row(**overrides: object) -> dict[str, object]:
    return {
        "model_group": "qwen3-max",
        "model_id": "node-a",
        "model": "moark/qwen3.8-max",
        "api_base": "https://api.moark.com/v1",
        "requests": 40,
        "failed_requests": 2,
        "streamed_requests": 38,
        "output_tokens": 8000,
        "peak_concurrency": 16,
        "first_request_at": "2026-10-22T11:00:00",
        "last_response_at": "2026-10-22T11:00:20",
        "ttft_p50": 210.0,
        "ttft_p95": 480.5,
        "ttft_p99": 610.0,
        "tpot_p50": 22.0,
        "tpot_p95": 35.0,
        "tpot_p99": 41.0,
        "e2e_p50": 4600.0,
        "e2e_p95": 7900.0,
        "e2e_p99": 9100.0,
        **overrides,
    }


def _client(role: LitellmUserRoles) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[user_api_key_auth] = lambda: UserAPIKeyAuth(api_key="sk-test", user_role=role)
    return TestClient(app)


class TestResolveWindow:
    def test_defaults_to_the_window_ending_now(self) -> None:
        assert resolve_window(None, None, NOW) == (NOW - QOS_DEFAULT_WINDOW, NOW)

    def test_timezone_aware_bounds_are_compared_in_utc(self) -> None:
        start, end = resolve_window(
            datetime(2026, 10, 22, 19, 0, tzinfo=timezone(timedelta(hours=8))),
            datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc),
            NOW,
        )
        assert (start, end) == (datetime(2026, 10, 22, 11, 0), datetime(2026, 10, 22, 12, 0))

    def test_rejects_an_empty_or_inverted_window(self) -> None:
        with pytest.raises(HTTPException) as error:
            resolve_window(NOW, NOW, NOW)
        assert error.value.status_code == 400

    def test_rejects_windows_longer_than_the_maximum(self) -> None:
        with pytest.raises(HTTPException) as error:
            resolve_window(NOW - QOS_MAX_WINDOW - timedelta(seconds=1), NOW, NOW)
        assert error.value.status_code == 400
        assert resolve_window(NOW - QOS_MAX_WINDOW, NOW, NOW)[0] == NOW - QOS_MAX_WINDOW


class TestQosSummaryEndpoint:
    def test_non_admin_keys_cannot_read_qos_metrics(self) -> None:
        with patch("litellm.proxy.proxy_server.prisma_client", MagicMock()):
            response = _client(LitellmUserRoles.INTERNAL_USER).get("/qos/summary")
        assert response.status_code == 403

    def test_rates_are_derived_from_the_active_span_and_filters_reach_both_queries(self) -> None:
        prisma = MagicMock()
        prisma.db.query_raw = AsyncMock(side_effect=[[_row(model_id="", api_base="")], [_row()]])

        with patch("litellm.proxy.proxy_server.prisma_client", prisma):
            response = _client(LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY).get(
                "/qos/summary",
                params={
                    "start_time": "2026-10-22T10:00:00",
                    "end_time": "2026-10-22T12:00:00",
                    "model_group": "qwen3-max",
                    "tag": "qos-run-1",
                },
            )

        assert response.status_code == 200
        window_and_filters: Final = (datetime(2026, 10, 22, 10), datetime(2026, 10, 22, 12), "qwen3-max", "qos-run-1")
        assert [call.args for call in prisma.db.query_raw.await_args_list] == [
            (MODEL_GROUP_SUMMARY_SQL, *window_and_filters),
            (DEPLOYMENT_SUMMARY_SQL, *window_and_filters),
        ]
        body: Final = response.json()
        group: Final = body["model_groups"][0]
        assert group["requests_per_second"] == pytest.approx(40 / 20)
        assert group["output_tokens_per_second"] == pytest.approx(8000 / 20)
        assert group["ttft_ms"] == {"p50": 210.0, "p95": 480.5, "p99": 610.0}
        assert "model_id" not in group
        deployment: Final = body["deployments"][0]
        assert (deployment["model_id"], deployment["api_base"]) == ("node-a", "https://api.moark.com/v1")
        assert deployment["tpot_ms"]["p95"] == 35.0
        assert body["tag"] == "qos-run-1"
        assert body["start_time"] == "2026-10-22T10:00:00Z"
        assert group["first_request_at"] == "2026-10-22T11:00:00Z"

    def test_a_single_instant_of_traffic_reports_zero_rates_instead_of_dividing_by_zero(self) -> None:
        prisma = MagicMock()
        instant: Final = _row(last_response_at="2026-10-22T11:00:00", ttft_p50=None, ttft_p95=None, ttft_p99=None)
        prisma.db.query_raw = AsyncMock(side_effect=[[instant], [instant]])

        with patch("litellm.proxy.proxy_server.prisma_client", prisma):
            response = _client(LitellmUserRoles.PROXY_ADMIN).get("/qos/summary")

        group: Final = response.json()["model_groups"][0]
        assert (group["requests_per_second"], group["output_tokens_per_second"]) == (0.0, 0.0)
        assert group["ttft_ms"] == {"p50": None, "p95": None, "p99": None}


_PLAN: Final = {"model_group": "qwen3-max", "concurrency": [1, 4], "requests_per_worker": 2, "max_tokens": 128}


class TestBenchmarkEndpoints:
    def test_only_full_proxy_admins_can_start_a_benchmark(self) -> None:
        with patch("litellm.proxy.management_endpoints.qos_endpoints.start_benchmark") as start:
            response = _client(LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY).post("/qos/benchmarks", json=_PLAN)
        assert response.status_code == 403
        start.assert_not_called()

    def test_unknown_models_are_rejected_before_any_traffic_is_sent(self) -> None:
        llm_router = MagicMock()
        llm_router.get_model_names.return_value = ["other-model"]
        with (
            patch("litellm.proxy.proxy_server.llm_router", llm_router),
            patch("litellm.proxy.management_endpoints.qos_endpoints.start_benchmark") as start,
        ):
            response = _client(LitellmUserRoles.PROXY_ADMIN).post("/qos/benchmarks", json=_PLAN)
        assert response.status_code == 404
        start.assert_not_called()

    def test_starting_a_benchmark_targets_this_gateway_with_the_master_key(self) -> None:
        llm_router = MagicMock()
        llm_router.get_model_names.return_value = ["qwen3-max"]
        with (
            patch("litellm.proxy.proxy_server.llm_router", llm_router),
            patch("litellm.proxy.proxy_server.master_key", "sk-master"),
            patch("litellm.proxy.management_endpoints.qos_endpoints.start_benchmark") as start,
        ):
            response = _client(LitellmUserRoles.PROXY_ADMIN).post("/qos/benchmarks", json=_PLAN)

        assert response.status_code == 200
        body: Final = response.json()
        assert body["total_requests"] == (1 + 4) * 2
        assert body["run_id"].startswith("qos-")
        base_url, api_key, run_id, plan = start.call_args.args
        assert base_url.startswith("http://127.0.0.1:")
        assert (api_key, run_id, plan.concurrency) == ("sk-master", body["run_id"], (1, 4))

    def test_run_details_reject_ids_that_are_not_benchmark_runs(self) -> None:
        with patch("litellm.proxy.proxy_server.prisma_client", MagicMock()):
            response = _client(LitellmUserRoles.PROXY_ADMIN).get("/qos/benchmarks/not-a-run")
        assert response.status_code == 400

    def test_run_details_list_levels_by_concurrency_parsed_from_their_tags(self) -> None:
        prisma = MagicMock()
        prisma.db.query_raw = AsyncMock(
            side_effect=[
                [_row(model_id="", level_tag="qos-run-1@c16"), _row(model_id="", level_tag="qos-run-1@c4")],
                [_row()],
            ]
        )
        with patch("litellm.proxy.proxy_server.prisma_client", prisma):
            response = _client(LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY).get("/qos/benchmarks/qos-run-1")

        assert response.status_code == 200
        assert [level["concurrency"] for level in response.json()["levels"]] == [4, 16]
        assert response.json()["deployments"][0]["model_id"] == "node-a"
        level_query, deployment_query = prisma.db.query_raw.await_args_list
        assert (level_query.args[0], level_query.args[3:]) == (BENCHMARK_LEVEL_SUMMARY_SQL, (None, "qos-run-1"))
        assert (deployment_query.args[0], deployment_query.args[3:]) == (DEPLOYMENT_SUMMARY_SQL, (None, "qos-run-1"))
