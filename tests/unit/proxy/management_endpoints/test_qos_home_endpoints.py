from typing import Final
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.management_endpoints.qos_activity import MODELS_ADDED_SQL, NODE_TRANSITIONS_SQL
from litellm.proxy.management_endpoints.qos_home_endpoints import router
from litellm.proxy.management_endpoints.qos_summary import BENCHMARK_RUNS_SQL


def _client(role: LitellmUserRoles | None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[user_api_key_auth] = lambda: UserAPIKeyAuth(
        api_key="sk-test", user_role=role, user_email="admin@example.com"
    )
    return TestClient(app)


def _repository(board: dict[str, object] | None, saved: bool = True) -> MagicMock:
    repository = MagicMock()
    repository.get_param = AsyncMock(return_value=None if board is None else MagicMock(param_value=board))
    repository.set_param_if_revision = AsyncMock(return_value=saved)
    return repository


def _patched(repository: MagicMock):
    return patch("litellm.proxy.management_endpoints.qos_home_endpoints.ConfigRepository", return_value=repository)


class TestAnnouncements:
    def test_every_user_reads_announcements_but_only_admins_post_them(self) -> None:
        repository: Final = _repository(None)
        with patch("litellm.proxy.proxy_server.prisma_client", MagicMock()), _patched(repository):
            listed = _client(LitellmUserRoles.INTERNAL_USER_VIEW_ONLY).get("/qos/announcements")
            refused = _client(LitellmUserRoles.INTERNAL_USER).post("/qos/announcements", json={"title": "hi"})

        assert (listed.status_code, listed.json()) == (200, {"announcements": []})
        assert refused.status_code == 403
        repository.set_param_if_revision.assert_not_awaited()

    def test_an_admin_posts_an_announcement_signed_with_their_email(self) -> None:
        repository: Final = _repository(None)
        with patch("litellm.proxy.proxy_server.prisma_client", MagicMock()), _patched(repository):
            response = _client(LitellmUserRoles.PROXY_ADMIN).post(
                "/qos/announcements", json={"title": "Maintenance", "body": "Saturday 02:00"}
            )

        assert response.status_code == 200, response.text
        (announcement,) = response.json()["announcements"]
        assert (announcement["title"], announcement["author"]) == ("Maintenance", "admin@example.com")

    def test_a_post_that_raced_another_change_asks_to_retry(self) -> None:
        with patch("litellm.proxy.proxy_server.prisma_client", MagicMock()), _patched(_repository(None, saved=False)):
            response = _client(LitellmUserRoles.PROXY_ADMIN).post("/qos/announcements", json={"title": "Maintenance"})
        assert response.status_code == 409

    def test_deleting_an_unknown_announcement_is_not_found(self) -> None:
        with patch("litellm.proxy.proxy_server.prisma_client", MagicMock()), _patched(_repository(None)):
            response = _client(LitellmUserRoles.PROXY_ADMIN).delete("/qos/announcements/missing")
        assert response.status_code == 404

    def test_an_empty_title_is_rejected(self) -> None:
        with patch("litellm.proxy.proxy_server.prisma_client", MagicMock()), _patched(_repository(None)):
            response = _client(LitellmUserRoles.PROXY_ADMIN).post("/qos/announcements", json={"title": ""})
        assert response.status_code == 422


class TestActivity:
    def test_merges_node_benchmark_and_model_events_newest_first(self) -> None:
        prisma = MagicMock()
        prisma.db.query_raw = AsyncMock(
            side_effect=[
                [
                    {
                        "model_name": "GLM-5.3",
                        "model_id": "node-a",
                        "status": "unhealthy",
                        "error_message": "timeout",
                        "checked_at": "2026-10-26T09:00:00",
                    }
                ],
                [
                    {
                        "run_id": "qos-run-1",
                        "model_group": "GLM-5.3",
                        "requests": 40,
                        "failed_requests": 0,
                        "crosstalk_responses": 2,
                        "started_at": "2026-10-26T10:00:00",
                        "last_response_at": "2026-10-26T10:05:00",
                    }
                ],
                [{"model_name": "Qwen3", "created_at": "2026-10-26T08:00:00", "created_by": "admin"}],
            ]
        )
        with (
            patch("litellm.proxy.proxy_server.prisma_client", prisma),
            patch("litellm.proxy.proxy_server.llm_router", None),
        ):
            response = _client(LitellmUserRoles.INTERNAL_USER).get("/qos/home/activity", params={"days": 3})

        assert response.status_code == 200, response.text
        assert [event["kind"] for event in response.json()["events"]] == ["benchmark", "node_down", "model_added"]
        assert response.json()["events"][0]["crosstalk_responses"] == 2
        assert [call.args[0] for call in prisma.db.query_raw.await_args_list] == [
            NODE_TRANSITIONS_SQL,
            BENCHMARK_RUNS_SQL,
            MODELS_ADDED_SQL,
        ]

    @pytest.mark.parametrize("path", ["/qos/home/activity", "/qos/announcements", "/qos/home/news"])
    def test_a_key_without_a_user_role_sees_nothing(self, path: str) -> None:
        with patch("litellm.proxy.proxy_server.prisma_client", MagicMock()):
            response = _client(None).get(path)
        assert response.status_code == 403
