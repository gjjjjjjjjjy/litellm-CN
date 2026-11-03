import json
from datetime import datetime, timezone
from typing import Final
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.management_endpoints.qos_summary import QOS_MAX_WINDOW
from litellm.proxy.management_endpoints.qos_video_evaluation_endpoints import (
    LATEST_PRICES_SQL,
    PRICE_WINDOW,
    USED_PROMPTS_SQL,
    MediaProbe,
    media_probe,
    router,
)
from litellm.proxy.management_endpoints.qos_video_reviews import RECORD_AI_REVIEW_SQL

PROMPT: Final = "夜晚刚下过雨的街道，镜头从左向右缓慢平移，一个穿黄色雨衣的人骑着自行车从画面左侧骑向右侧"
SCORE: Final = {
    "judge": "qwen3.8-27b",
    "frames": 4,
    "overall": 3,
    "visual": 4,
    "detail": 2,
    "motion": 3,
    "alignment": 4,
    "physics": 2,
    "reasons": {"detail": "招牌上的字糊了", "physics": "积水里没有倒影"},
    "checklist": [{"requirement": "招牌写着“咖啡”", "met": False, "evidence": "第 2 秒的字看不清"}],
    "problems": [{"second": 2, "problem": "招牌的字变形"}],
}


class _Probe:
    """Answers the gateway the way the media probe does, and keeps what it was asked."""

    def __init__(self, status: int = 200, answer: bytes = b"{}") -> None:
        self.status = status
        self.answer = answer
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, content=self.answer)

    def media_probe(self) -> MediaProbe:
        return MediaProbe(
            base_url="http://media-probe:8090", token="sk-master", transport=httpx.MockTransport(self.handle)
        )


def _client(role: LitellmUserRoles | None, probe: MediaProbe | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[user_api_key_auth] = lambda: UserAPIKeyAuth(api_key="sk-test", user_role=role)
    app.dependency_overrides[media_probe] = lambda: probe
    return TestClient(app)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _deployment(name: str, mode: str, qos_probe: dict[str, object] | None) -> dict[str, object]:
    info: Final = {"mode": mode} if qos_probe is None else {"mode": mode, "qos_probe": qos_probe}
    return {"model_name": name, "litellm_params": {"model": f"moark/{name}"}, "model_info": info}


@pytest.mark.parametrize("role", (None, LitellmUserRoles.INTERNAL_USER, LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY))
@pytest.mark.parametrize(
    ("method", "path", "body"),
    (
        ("post", "/qos/videos/evaluations", {"prompt": PROMPT}),
        ("post", "/qos/videos/evaluations/prompt", None),
        ("put", "/qos/videos/evaluations/score?video_id=video-1", SCORE),
    ),
)
def test_only_admins_who_may_change_data_start_runs_write_prompts_or_store_ai_ratings(
    role: LitellmUserRoles | None, method: str, path: str, body: dict[str, object] | None
) -> None:
    probe: Final = _Probe()
    prisma: Final = MagicMock()
    prisma.db.query_raw = AsyncMock(return_value=[])

    with patch("litellm.proxy.proxy_server.prisma_client", prisma):
        response: Final = _client(role, probe.media_probe()).request(method, path, json=body)

    assert response.status_code == 403
    assert probe.requests == []
    prisma.db.query_raw.assert_not_awaited()


def test_only_admins_see_what_a_run_would_offer() -> None:
    prisma: Final = MagicMock()
    prisma.db.query_raw = AsyncMock(return_value=[])

    with patch("litellm.proxy.proxy_server.prisma_client", prisma):
        response: Final = _client(LitellmUserRoles.INTERNAL_USER).get("/qos/videos/evaluations/options")

    assert response.status_code == 403
    prisma.db.query_raw.assert_not_awaited()


def test_a_runs_options_list_each_probed_video_model_once_with_its_latest_price_and_the_earlier_prompts() -> None:
    llm_router: Final = MagicMock()
    llm_router.get_model_list = MagicMock(
        return_value=[
            _deployment("LTX-2", "video_generation", {"image": True}),
            _deployment("LTX-2", "video_generation", {"image": True}),
            _deployment("MiniMax-H3", "video_generation", {"params": {"task": "t2va"}}),
            _deployment("Wan2.7", "video_generation", None),
            _deployment("IndexTTS-2", "audio_speech", {}),
        ]
    )
    used_prompt: Final = {"prompt": PROMPT, "last_used": datetime(2026, 11, 3, 9, 0), "videos": 3}
    prisma: Final = MagicMock()
    prisma.db.query_raw = AsyncMock(
        side_effect=[[used_prompt], [{"model_group": "LTX-2", "last_price": 1.5, "currency": "CNY"}]]
    )
    before: Final = _utc_now()

    with (
        patch("litellm.proxy.proxy_server.prisma_client", prisma),
        patch("litellm.proxy.proxy_server.llm_router", llm_router),
    ):
        response: Final = _client(LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY, _Probe().media_probe()).get(
            "/qos/videos/evaluations/options"
        )

    after: Final = _utc_now()
    assert response.status_code == 200, response.text
    assert response.json() == {
        "available": True,
        "models": [
            {"model_group": "LTX-2", "image_to_video": True, "last_price": 1.5, "currency": "CNY"},
            {"model_group": "MiniMax-H3", "image_to_video": False, "last_price": None, "currency": None},
        ],
        "prompts": [{"prompt": PROMPT, "last_used": "2026-11-03T09:00:00Z", "videos": 3}],
    }
    (prompts_sql, prompts_since), (prices_sql, prices_since) = (
        call.args for call in prisma.db.query_raw.await_args_list
    )
    assert (prompts_sql, prices_sql) == (USED_PROMPTS_SQL, LATEST_PRICES_SQL)
    assert before - QOS_MAX_WINDOW <= prompts_since <= after - QOS_MAX_WINDOW
    assert before - PRICE_WINDOW <= prices_since <= after - PRICE_WINDOW


def test_a_runs_options_say_none_can_start_while_no_media_probe_is_set_up() -> None:
    prisma: Final = MagicMock()
    prisma.db.query_raw = AsyncMock(return_value=[])

    with (
        patch("litellm.proxy.proxy_server.prisma_client", prisma),
        patch("litellm.proxy.proxy_server.llm_router", None),
    ):
        response: Final = _client(LitellmUserRoles.PROXY_ADMIN).get("/qos/videos/evaluations/options")

    assert response.status_code == 200, response.text
    assert response.json() == {"available": False, "models": [], "prompts": []}


def test_starting_a_run_hands_the_trimmed_prompt_to_the_probe_with_the_gateways_key() -> None:
    started: Final = {"prompt": PROMPT, "models": ["MiniMax-H3", "LTX-2", "Wan2_2-I2V-A14B"]}
    probe: Final = _Probe(answer=json.dumps(started).encode())

    response: Final = _client(LitellmUserRoles.PROXY_ADMIN, probe.media_probe()).post(
        "/qos/videos/evaluations", json={"prompt": f"  {PROMPT}\n"}
    )

    assert response.status_code == 200, response.text
    assert response.json() == started
    (asked,) = probe.requests
    assert (asked.method, asked.url.path, asked.headers["authorization"]) == (
        "POST",
        "/evaluations",
        "Bearer sk-master",
    )
    assert json.loads(asked.content) == {"prompt": PROMPT}


def test_a_run_cannot_start_without_a_media_probe_and_the_error_says_how_to_set_one_up() -> None:
    response: Final = _client(LitellmUserRoles.PROXY_ADMIN).post("/qos/videos/evaluations", json={"prompt": PROMPT})

    assert response.status_code == 503
    assert "QOS_MEDIA_PROBE_URL" in response.json()["detail"]


class _Unreachable:
    def handle(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)


@pytest.mark.parametrize(
    ("probe", "reason"),
    (
        (_Probe(status=500, answer=b"evaluation thread crashed").media_probe(), "500: evaluation thread crashed"),
        (_Probe(answer=b"<html>not json</html>").media_probe(), "not readable"),
        (MediaProbe("http://media-probe:8090", "sk-master", httpx.MockTransport(_Unreachable().handle)), "reach"),
    ),
)
def test_a_probe_that_fails_answers_oddly_or_cannot_be_reached_is_a_bad_gateway(probe: MediaProbe, reason: str) -> None:
    response: Final = _client(LitellmUserRoles.PROXY_ADMIN, probe).post(
        "/qos/videos/evaluations", json={"prompt": PROMPT}
    )

    assert response.status_code == 502
    assert reason in response.json()["detail"]


@pytest.mark.parametrize("prompt", ("", "   \n", "雨" * 501))
def test_an_empty_or_overlong_prompt_is_rejected_before_the_probe_is_asked(prompt: str) -> None:
    probe: Final = _Probe()

    response: Final = _client(LitellmUserRoles.PROXY_ADMIN, probe.media_probe()).post(
        "/qos/videos/evaluations", json={"prompt": prompt}
    )

    assert response.status_code == 422
    assert probe.requests == []


def test_a_new_prompt_comes_from_the_probe_which_is_told_to_avoid_the_ten_most_recent_ones() -> None:
    recent: Final = [
        {"prompt": f"第 {index} 个 Prompt", "last_used": datetime(2026, 11, 3), "videos": 3} for index in range(12)
    ]
    prisma: Final = MagicMock()
    prisma.db.query_raw = AsyncMock(return_value=recent)
    probe: Final = _Probe(answer=json.dumps({"prompt": PROMPT}).encode())

    with patch("litellm.proxy.proxy_server.prisma_client", prisma):
        response: Final = _client(LitellmUserRoles.PROXY_ADMIN, probe.media_probe()).post(
            "/qos/videos/evaluations/prompt"
        )

    assert response.status_code == 200, response.text
    assert response.json() == {"prompt": PROMPT}
    (asked,) = probe.requests
    assert (asked.url.path, json.loads(asked.content)) == (
        "/prompts",
        {"avoid": [f"第 {index} 个 Prompt" for index in range(10)]},
    )
    ((sql, _since),) = (call.args for call in prisma.db.query_raw.await_args_list)
    assert sql == USED_PROMPTS_SQL


def test_an_ai_rating_is_kept_on_the_video_with_the_time_it_was_saved() -> None:
    prisma: Final = MagicMock()
    prisma.db.query_raw = AsyncMock(return_value=[{"request_id": "video-1"}])

    with patch("litellm.proxy.proxy_server.prisma_client", prisma):
        response: Final = _client(LitellmUserRoles.PROXY_ADMIN).put(
            "/qos/videos/evaluations/score?video_id=video-1", json=SCORE
        )

    assert response.status_code == 200, response.text
    saved: Final = response.json()
    assert {key: value for key, value in saved.items() if key != "reviewed_at"} == {
        **SCORE,
        "reasons": {
            "visual": "",
            "detail": "招牌上的字糊了",
            "motion": "",
            "alignment": "",
            "physics": "积水里没有倒影",
        },
        "problems": [{"second": 2.0, "problem": "招牌的字变形"}],
    }
    assert datetime.fromisoformat(saved["reviewed_at"]).tzinfo is not None
    ((sql, video_id, stored),) = (call.args for call in prisma.db.query_raw.await_args_list)
    assert (sql, video_id, json.loads(stored)) == (RECORD_AI_REVIEW_SQL, "video-1", saved)


def test_an_ai_rating_of_a_video_the_probe_did_not_make_is_not_found() -> None:
    prisma: Final = MagicMock()
    prisma.db.query_raw = AsyncMock(return_value=[])

    with patch("litellm.proxy.proxy_server.prisma_client", prisma):
        response: Final = _client(LitellmUserRoles.PROXY_ADMIN).put(
            "/qos/videos/evaluations/score?video_id=not-a-probe-video", json=SCORE
        )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "score",
    (
        {**SCORE, "detail": 0},
        {**SCORE, "overall": 6},
        {key: value for key, value in SCORE.items() if key != "physics"},
        {**SCORE, "frames": 0},
        {**SCORE, "audio": 4},
        {**SCORE, "reasons": {"visual": "x" * 501}},
    ),
)
def test_ai_ratings_outside_one_to_five_or_missing_a_rating_are_rejected_before_writing(
    score: dict[str, object],
) -> None:
    prisma: Final = MagicMock()
    prisma.db.query_raw = AsyncMock()

    with patch("litellm.proxy.proxy_server.prisma_client", prisma):
        response: Final = _client(LitellmUserRoles.PROXY_ADMIN).put(
            "/qos/videos/evaluations/score?video_id=video-1", json=score
        )

    assert response.status_code == 422
    prisma.db.query_raw.assert_not_awaited()
