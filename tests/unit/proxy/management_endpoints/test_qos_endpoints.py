import json
from datetime import datetime, timedelta, timezone
from typing import Final
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from litellm.llms.openai_like.json_loader import JSONProviderRegistry
from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.management_endpoints.qos_endpoints import (
    BENCHMARK_DELETE_SQL,
    BENCHMARK_DEPLOYMENT_LEVEL_SUMMARY_SQL,
    BENCHMARK_INTERFERENCE_SQL,
    BENCHMARK_LEVEL_SUMMARY_SQL,
    DEPLOYMENT_SUMMARY_SQL,
    MODEL_GROUP_SUMMARY_SQL,
    QOS_DEFAULT_WINDOW,
    QOS_MAX_WINDOW,
    resolve_window,
    router,
)
from litellm.proxy.management_endpoints.qos_response_check import record_response_checks
from litellm.proxy.management_endpoints.qos_trends import TREND_SQL

NOW: Final = datetime(2026, 10, 22, 12, 0, 0)


def _row(**overrides: object) -> dict[str, object]:
    return {
        "model_group": "qwen3-max",
        "model_id": "node-a",
        "model": "moark/qwen3.8-max",
        "api_base": "https://api.moark.com/v1",
        "custom_llm_provider": "moark",
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
        "checked_responses": 40,
        "crosstalk_responses": 0,
        "marker_missing_responses": 0,
        **overrides,
    }


def _router(deployments: dict[str, MagicMock]) -> MagicMock:
    """A router serving these deployments, keyed by id; like the real one it names a model once per deployment."""
    llm_router = MagicMock()
    llm_router.get_model_names.return_value = [deployment.model_name for deployment in deployments.values()]
    llm_router.get_model_ids.side_effect = lambda model_name=None: [
        model_id for model_id, deployment in deployments.items() if model_name in (None, deployment.model_name)
    ]
    llm_router.get_deployment.side_effect = deployments.get
    return llm_router


def _deployment(model_name: str, model: str, api_base: str | None, provider: str | None = None) -> MagicMock:
    deployment = MagicMock()
    deployment.model_name = model_name
    deployment.litellm_params.model = model
    deployment.litellm_params.api_base = api_base
    deployment.litellm_params.custom_llm_provider = provider
    return deployment


_QWEN_ON_TWO_PROVIDERS: Final = {
    "node-moark": _deployment("qwen3-max", "Qwen3-Max", None, "moark"),
    "node-gitee": _deployment("qwen3-max", "openai/Qwen3-Max", "https://ai.gitee.com/v1"),
}


def _interference(model_id: str, level_tag: str, same_deployment: int, same_endpoint: int) -> dict[str, object]:
    return {
        "model_id": model_id,
        "level_tag": level_tag,
        "same_deployment": same_deployment,
        "same_endpoint": same_endpoint,
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

        with (
            patch("litellm.proxy.proxy_server.prisma_client", prisma),
            patch("litellm.proxy.proxy_server.llm_router", _router(_QWEN_ON_TWO_PROVIDERS)),
        ):
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
        calls: Final = [call.args for call in prisma.db.query_raw.await_args_list]
        assert [call[:5] for call in calls] == [
            (MODEL_GROUP_SUMMARY_SQL, *window_and_filters),
            (DEPLOYMENT_SUMMARY_SQL, *window_and_filters),
        ]
        deployment_groups: Final = {"node-moark": "qwen3-max", "node-gitee": "qwen3-max"}
        assert [json.loads(call[5]) for call in calls] == [deployment_groups, deployment_groups]
        body: Final = response.json()
        group: Final = body["model_groups"][0]
        assert group["requests_per_second"] == pytest.approx(40 / 20)
        assert group["output_tokens_per_second"] == pytest.approx(8000 / 20)
        assert group["ttft_ms"] == {"p50": 210.0, "p95": 480.5, "p99": 610.0}
        assert group["response_checks"] == {"checked": 40, "crosstalk": 0, "marker_missing": 0}
        assert "model_id" not in group
        deployment: Final = body["deployments"][0]
        assert (deployment["model_id"], deployment["api_base"], deployment["vendor"]) == (
            "node-a",
            "https://api.moark.com/v1",
            "moark",
        )
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
            patch("litellm.proxy.proxy_server.prisma_client", MagicMock()),
            patch("litellm.proxy.management_endpoints.qos_endpoints.start_benchmark") as start,
        ):
            response = _client(LitellmUserRoles.PROXY_ADMIN).post("/qos/benchmarks", json=_PLAN)
        assert response.status_code == 404
        start.assert_not_called()

    def test_starting_a_benchmark_targets_this_gateway_with_the_master_key(self) -> None:
        prisma: Final = MagicMock()
        with (
            patch("litellm.proxy.proxy_server.llm_router", _router(_QWEN_ON_TWO_PROVIDERS)),
            patch("litellm.proxy.proxy_server.master_key", "sk-master"),
            patch("litellm.proxy.proxy_server.prisma_client", prisma),
            patch("litellm.proxy.management_endpoints.qos_endpoints.start_benchmark") as start,
        ):
            response = _client(LitellmUserRoles.PROXY_ADMIN).post("/qos/benchmarks", json=_PLAN)

        assert response.status_code == 200
        body: Final = response.json()
        assert body["total_requests"] == (1 + 4) * 2
        assert body["run_id"].startswith("qos-")
        base_url, api_key, run_id, plan, record_checks = start.call_args.args
        assert (record_checks.func, record_checks.args) == (record_response_checks, (prisma,))
        assert base_url.startswith("http://127.0.0.1:")
        assert (api_key, run_id, plan.concurrency, plan.targets) == (
            "sk-master",
            body["run_id"],
            (1, 4),
            ("qwen3-max",),
        )

    def test_a_provider_comparison_only_accepts_deployments_of_the_chosen_model(self) -> None:
        stray: Final = {**_QWEN_ON_TWO_PROVIDERS, "node-glm": _deployment("glm-5", "GLM-5", "https://ai.gitee.com/v1")}
        with (
            patch("litellm.proxy.proxy_server.llm_router", _router(stray)),
            patch("litellm.proxy.proxy_server.prisma_client", MagicMock()),
            patch("litellm.proxy.management_endpoints.qos_endpoints.start_benchmark") as start,
        ):
            response = _client(LitellmUserRoles.PROXY_ADMIN).post(
                "/qos/benchmarks", json={**_PLAN, "deployment_ids": ["node-moark", "node-glm"]}
            )
        assert response.status_code == 400, response.text
        assert "node-glm" in response.json()["detail"]
        start.assert_not_called()

    def test_a_provider_comparison_runs_the_plan_once_per_deployment(self) -> None:
        with (
            patch("litellm.proxy.proxy_server.llm_router", _router(_QWEN_ON_TWO_PROVIDERS)),
            patch("litellm.proxy.proxy_server.master_key", "sk-master"),
            patch("litellm.proxy.proxy_server.prisma_client", MagicMock()),
            patch("litellm.proxy.management_endpoints.qos_endpoints.start_benchmark") as start,
        ):
            response = _client(LitellmUserRoles.PROXY_ADMIN).post(
                "/qos/benchmarks", json={**_PLAN, "deployment_ids": ["node-gitee", "node-moark"]}
            )

        assert response.status_code == 200, response.text
        body: Final = response.json()
        assert (body["deployment_ids"], body["total_requests"]) == (["node-gitee", "node-moark"], (1 + 4) * 2 * 2)
        assert start.call_args.args[3].targets == ("node-gitee", "node-moark")

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
                [
                    _row(model_id="node-moark", level_tag="qos-run-1@c16"),
                    _row(model_id="node-gitee", level_tag="qos-run-1@c4"),
                    _row(model_id="node-moark", level_tag="qos-run-1@c4", ttft_p50=150.0, crosstalk_responses=3),
                ],
                [
                    _interference("node-moark", "qos-run-1@c16", same_deployment=0, same_endpoint=0),
                    _interference("node-gitee", "qos-run-1@c4", same_deployment=2, same_endpoint=1),
                    _interference("node-moark", "qos-run-1@c4", same_deployment=5, same_endpoint=0),
                ],
            ]
        )
        with (
            patch("litellm.proxy.proxy_server.prisma_client", prisma),
            patch("litellm.proxy.proxy_server.llm_router", _router(_QWEN_ON_TWO_PROVIDERS)),
        ):
            response = _client(LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY).get("/qos/benchmarks/qos-run-1")

        assert response.status_code == 200
        body: Final = response.json()
        assert [level["concurrency"] for level in body["levels"]] == [4, 16]
        assert body["deployments"][0]["model_id"] == "node-a"
        assert [(level["concurrency"], level["model_id"]) for level in body["deployment_levels"]] == [
            (4, "node-gitee"),
            (4, "node-moark"),
            (16, "node-moark"),
        ]
        moark_at_4: Final = body["deployment_levels"][1]
        assert moark_at_4["ttft_ms"]["p50"] == 150.0
        assert moark_at_4["response_checks"]["crosstalk"] == 3
        assert moark_at_4["interference"] == {"same_deployment": 5, "same_endpoint": 0}
        assert [level["interference"] for level in body["levels"]] == [
            {"same_deployment": 2 + 5, "same_endpoint": 1},
            {"same_deployment": 0, "same_endpoint": 0},
        ]
        calls: Final = prisma.db.query_raw.await_args_list
        assert [(call.args[0], call.args[3:5]) for call in calls[:3]] == [
            (BENCHMARK_LEVEL_SUMMARY_SQL, (None, "qos-run-1")),
            (DEPLOYMENT_SUMMARY_SQL, (None, "qos-run-1")),
            (BENCHMARK_DEPLOYMENT_LEVEL_SUMMARY_SQL, (None, "qos-run-1")),
        ]
        assert (calls[3].args[0], calls[3].args[3]) == (BENCHMARK_INTERFERENCE_SQL, "qos-run-1")

    def test_targets_list_each_model_with_the_provider_and_endpoint_of_every_deployment(self) -> None:
        with patch("litellm.proxy.proxy_server.llm_router", _router(_QWEN_ON_TWO_PROVIDERS)):
            response = _client(LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY).get("/qos/targets")

        assert response.status_code == 200, response.text
        (model,) = response.json()["models"]
        moark = JSONProviderRegistry.get("moark")
        assert moark is not None
        assert model == {
            "model_group": "qwen3-max",
            "deployments": [
                {
                    "model_id": "node-moark",
                    "provider": "moark",
                    "vendor": "moark",
                    "api_base": moark.base_url,
                    "upstream_model": "Qwen3-Max",
                },
                {
                    "model_id": "node-gitee",
                    "provider": "openai",
                    "vendor": "ai.gitee.com",
                    "api_base": "https://ai.gitee.com/v1",
                    "upstream_model": "Qwen3-Max",
                },
            ],
        }


_OVERALL: Final = {
    "requests": 40,
    "failed_requests": 2,
    "output_tokens": 7200,
    "checked_responses": 0,
    "crosstalk_responses": 0,
    "marker_missing_responses": 0,
    "ttft_p50": 210.0,
    "ttft_p95": 480.0,
    "ttft_p99": 600.0,
    "tpot_p50": 22.0,
    "tpot_p95": 35.0,
    "tpot_p99": 41.0,
}


class TestTrendsEndpoint:
    def test_compares_the_window_with_the_one_before_it_and_maps_deployment_ids_to_models(self) -> None:
        trend_row: Final = {
            "model_group": "qwen3-max",
            "model_id": "node-moark",
            "bucket_start": "2026-10-22T11:00:00",
            "api_base": "https://api.moark.com/v1",
            "custom_llm_provider": "moark",
            **{key: value for key, value in _OVERALL.items() if not key.endswith("_responses")},
        }
        prisma = MagicMock()
        prisma.db.query_raw = AsyncMock(side_effect=[[_OVERALL], [{**_OVERALL, "requests": 20}], [trend_row]])

        with (
            patch("litellm.proxy.proxy_server.prisma_client", prisma),
            patch("litellm.proxy.proxy_server.llm_router", _router(_QWEN_ON_TWO_PROVIDERS)),
        ):
            response = _client(LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY).get(
                "/qos/trends",
                params={
                    "start_time": "2026-10-22T10:00:00",
                    "end_time": "2026-10-22T12:00:00",
                    "group_by": "deployment",
                },
            )

        assert response.status_code == 200, response.text
        body: Final = response.json()
        assert (body["current"]["requests"], body["previous"]["requests"], body["bucket_seconds"]) == (40, 20, 120)
        assert body["current"]["output_tokens_per_second"] == pytest.approx(7200 / 7200)
        (series,) = body["series"]
        assert (series["model_id"], series["vendor"], len(series["points"])) == ("node-moark", "moark", 1)
        current_call, previous_call, trend_call = (call.args for call in prisma.db.query_raw.await_args_list)
        assert current_call[1:] == (datetime(2026, 10, 22, 10), datetime(2026, 10, 22, 12), None)
        assert previous_call[1:] == (datetime(2026, 10, 22, 8), datetime(2026, 10, 22, 10), None)
        assert (trend_call[0], trend_call[3]) == (TREND_SQL["deployment"], 120)
        assert json.loads(trend_call[5]) == {"node-moark": "qwen3-max", "node-gitee": "qwen3-max"}

    def test_internal_users_cannot_read_trends(self) -> None:
        with patch("litellm.proxy.proxy_server.prisma_client", MagicMock()):
            response = _client(LitellmUserRoles.INTERNAL_USER).get("/qos/trends")
        assert response.status_code == 403


class TestHealthEndpoint:
    def test_internal_users_cannot_read_node_health(self) -> None:
        with patch("litellm.proxy.proxy_server.prisma_client", MagicMock()):
            response = _client(LitellmUserRoles.INTERNAL_USER).get("/qos/health")
        assert response.status_code == 403

    def test_current_nodes_show_availability_and_latency_and_removed_models_are_left_out(self) -> None:
        history = [
            {
                "model_name": "GLM-5.3",
                "model_id": "node-a",
                "checks": 9,
                "failures": 1,
                "latest_status": "healthy",
                "last_error": "Timeout exceeded",
                "last_failure_at": "2026-10-23T01:58:49",
                "last_checked_at": "2026-10-23T05:14:25",
            },
            {
                "model_name": "Qwen3.8-27B",
                "model_id": "node-default-base",
                "checks": 3,
                "failures": 0,
                "latest_status": "healthy",
                "last_error": None,
                "last_failure_at": None,
                "last_checked_at": "2026-10-23T05:23:41",
            },
            {
                "model_name": "removed-model",
                "model_id": "node-gone",
                "checks": 2,
                "failures": 0,
                "latest_status": "healthy",
                "last_error": None,
                "last_failure_at": None,
                "last_checked_at": "2026-10-23T03:00:00",
            },
        ]
        probes = [
            {
                "model": "GLM-5.3",
                "api_base": "https://ai.gitee.com/v1/",
                "probes": 53,
                "p50": 1275.0,
                "p95": 2075.2,
                "p99": 4598.8,
                "last_probe_at": "2026-10-23T05:28:41",
            },
            {
                "model": "removed-model",
                "api_base": "https://ai.gitee.com/v1/",
                "probes": 12,
                "p50": 900.0,
                "p95": 1500.0,
                "p99": 1800.0,
                "last_probe_at": "2026-10-23T03:00:00",
            },
        ]
        prisma = MagicMock()
        prisma.db.query_raw = AsyncMock(side_effect=[history, probes])
        deployment = MagicMock()
        deployment.litellm_params.api_base = "https://ai.gitee.com/v1"
        deployment.litellm_params.model = "openai/GLM-5.3"
        deployment.litellm_params.custom_llm_provider = None
        default_base_deployment = MagicMock()
        default_base_deployment.litellm_params.api_base = None
        default_base_deployment.litellm_params.model = "Qwen3.8-27B"
        default_base_deployment.litellm_params.custom_llm_provider = "moark"
        deployments = {"node-a": deployment, "node-default-base": default_base_deployment}
        llm_router = MagicMock()
        llm_router.get_deployment.side_effect = deployments.get
        llm_router.get_model_ids.return_value = list(deployments)

        with (
            patch("litellm.proxy.proxy_server.prisma_client", prisma),
            patch("litellm.proxy.proxy_server.llm_router", llm_router),
        ):
            response = _client(LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY).get("/qos/health")

        assert response.status_code == 200
        node, default_base = response.json()["nodes"]
        assert node["availability"] == pytest.approx(8 / 9)
        assert (node["vendor"], node["api_base"], node["upstream_model"]) == (
            "ai.gitee.com",
            "https://ai.gitee.com/v1",
            "GLM-5.3",
        )
        assert (node["last_error"], node["last_failure_at"]) == ("Timeout exceeded", "2026-10-23T01:58:49Z")
        moark = JSONProviderRegistry.get("moark")
        assert moark is not None
        assert (default_base["vendor"], default_base["api_base"]) == ("moark", moark.base_url)
        (probe,) = response.json()["probes"]
        assert (probe["model"], probe["probes"]) == ("GLM-5.3", 53)
        assert probe["latency_ms"] == {"p50": 1275.0, "p95": 2075.2, "p99": 4598.8}
        assert probe["last_probe_at"] == "2026-10-23T05:28:41Z"


class TestBenchmarkDeletion:
    def test_only_full_proxy_admins_can_delete_a_run(self) -> None:
        prisma = MagicMock()
        prisma.db.query_raw = AsyncMock()
        with patch("litellm.proxy.proxy_server.prisma_client", prisma):
            response = _client(LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY).delete("/qos/benchmarks/qos-run-1")
        assert response.status_code == 403
        prisma.db.query_raw.assert_not_awaited()

    def test_ids_that_are_not_benchmark_runs_cannot_be_deleted(self) -> None:
        prisma = MagicMock()
        prisma.db.query_raw = AsyncMock()
        with patch("litellm.proxy.proxy_server.prisma_client", prisma):
            response = _client(LitellmUserRoles.PROXY_ADMIN).delete("/qos/benchmarks/litellm-internal-health-check")
        assert response.status_code == 400
        prisma.db.query_raw.assert_not_awaited()

    def test_deleting_a_run_removes_its_tagged_requests_and_reports_how_many(self) -> None:
        prisma = MagicMock()
        prisma.db.query_raw = AsyncMock(return_value=[{"deleted_requests": 42}])
        with patch("litellm.proxy.proxy_server.prisma_client", prisma):
            response = _client(LitellmUserRoles.PROXY_ADMIN).delete("/qos/benchmarks/qos-run-1")

        assert response.status_code == 200
        assert response.json() == {"run_id": "qos-run-1", "deleted_requests": 42}
        sql, since, run_id = prisma.db.query_raw.await_args.args
        assert (sql, run_id) == (BENCHMARK_DELETE_SQL, "qos-run-1")
        assert datetime.now(timezone.utc).replace(tzinfo=None) - since >= QOS_MAX_WINDOW
