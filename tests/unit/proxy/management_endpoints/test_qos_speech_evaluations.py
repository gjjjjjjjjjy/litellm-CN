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
from litellm.proxy.management_endpoints.qos_media_probe import MediaProbe, media_probe
from litellm.proxy.management_endpoints.qos_speech_evaluations import (
    RECORD_SPEECH_REVIEW_SQL,
    RECORD_TRANSCRIPT_SQL,
    SPEECH_RESULTS_SQL,
    router,
)

SENTENCE: Final = "今天天气很好，我们一起去公园散步，顺便买些水果回家。"
CREATED: Final = datetime(2026, 11, 4, 9, 0, 1)
WAV: Final = b"RIFF\x24\x00\x00\x00WAVEfmt "
MY_REVIEW: Final = {"overall": 4, "reviewed_at": "2026-11-04T09:30:00Z"}


class _Probe:
    """Answers the gateway the way the media probe does, and keeps what it was asked."""

    def __init__(self, status: int = 200, content: bytes = b"{}", content_type: str = "application/json") -> None:
        self.status = status
        self.content = content
        self.content_type = content_type
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, content=self.content, headers={"content-type": self.content_type})

    def media_probe(self) -> MediaProbe:
        return MediaProbe(
            base_url="http://media-probe:8090", token="sk-master", transport=httpx.MockTransport(self.handle)
        )


def _client(role: LitellmUserRoles | None, probe: MediaProbe | None = None, user_id: str | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[user_api_key_auth] = lambda: UserAPIKeyAuth(
        api_key="sk-test", user_role=role, user_id=user_id
    )
    app.dependency_overrides[media_probe] = lambda: probe
    return TestClient(app)


def _prisma(rows: list[dict[str, object]]) -> MagicMock:
    prisma: Final = MagicMock()
    prisma.db.query_raw = AsyncMock(return_value=rows)
    return prisma


def _row(**overrides: object) -> dict[str, object]:
    return {
        "request_id": "call-1",
        "created_at": CREATED,
        "model_group": "IndexTTS-2",
        "modality": "speech",
        "run": "20261104-090000-a1b2c3",
        "scheduled": True,
        "text": SENTENCE,
        "succeeded": True,
        "error": None,
        "latency_ms": 11259.5,
        "audio_seconds": 4.89,
        "transcript": None,
        "reviews": {},
        **overrides,
    }


@pytest.mark.parametrize("role", (None, LitellmUserRoles.INTERNAL_USER))
@pytest.mark.parametrize(
    ("method", "path", "body"),
    (
        ("get", "/qos/speech/evaluations", None),
        ("put", "/qos/speech/review?request_id=call-1", {"overall": 4}),
        ("get", "/qos/speech/evaluations/options", None),
        ("get", "/qos/speech/audio?request_id=call-1", None),
        ("get", "/qos/speech/recording", None),
    ),
)
def test_only_proxy_admins_see_rate_or_listen_to_the_speech_runs(
    role: LitellmUserRoles | None, method: str, path: str, body: dict[str, object] | None
) -> None:
    probe: Final = _Probe()
    prisma: Final = _prisma([])

    with patch("litellm.proxy.proxy_server.prisma_client", prisma):
        response: Final = _client(role, probe.media_probe()).request(method, path, json=body)

    assert response.status_code == 403
    assert probe.requests == []
    prisma.db.query_raw.assert_not_awaited()


@pytest.mark.parametrize("role", (LitellmUserRoles.INTERNAL_USER, LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY))
@pytest.mark.parametrize(
    ("path", "body"),
    (("/qos/speech/evaluations", None), ("/qos/speech/evaluations/transcript?request_id=call-1", {"text": "x"})),
)
def test_only_admins_who_may_change_data_start_runs_or_store_transcripts(
    role: LitellmUserRoles, path: str, body: dict[str, object] | None
) -> None:
    probe: Final = _Probe()
    prisma: Final = _prisma([])
    client: Final = _client(role, probe.media_probe())

    with patch("litellm.proxy.proxy_server.prisma_client", prisma):
        response: Final = client.post(path) if body is None else client.put(path, json=body)

    assert response.status_code == 403
    assert probe.requests == []
    prisma.db.query_raw.assert_not_awaited()


def test_the_speech_runs_show_each_request_with_the_callers_rating_and_why_a_failed_one_failed() -> None:
    rated: Final = _row(reviews={"admin-1": MY_REVIEW, "admin-2": {**MY_REVIEW, "overall": 1}})
    failed: Final = _row(
        request_id="call-2", succeeded=False, error="the resource pack does not cover this model", audio_seconds=None
    )
    heard: Final = _row(
        request_id="call-3", model_group="SenseVoiceSmall", modality="transcription", transcript="今天天气很好"
    )
    prisma: Final = _prisma([rated, failed, heard])
    llm_router: Final = MagicMock()
    llm_router.get_model_ids = MagicMock(return_value=[])

    with (
        patch("litellm.proxy.proxy_server.prisma_client", prisma),
        patch("litellm.proxy.proxy_server.llm_router", llm_router),
    ):
        response: Final = _client(LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY, user_id="admin-1").get(
            "/qos/speech/evaluations",
            params={"start_time": "2026-11-04T00:00:00", "end_time": "2026-11-04T12:00:00"},
        )

    assert response.status_code == 200, response.text
    first, second, third = response.json()["results"]
    assert (first["reviews"], first["overall"], first["my_review"]["overall"], first["error"]) == (2, 2.5, 4, None)
    assert (first["run"], first["scheduled"], first["text"], first["audio_seconds"]) == (
        "20261104-090000-a1b2c3",
        True,
        SENTENCE,
        4.89,
    )
    assert (second["succeeded"], second["error"], second["reviews"], second["my_review"]) == (
        False,
        "the resource pack does not cover this model",
        0,
        None,
    )
    assert (third["modality"], third["transcript"]) == ("transcription", "今天天气很好")
    ((sql, *params),) = (call.args for call in prisma.db.query_raw.await_args_list)
    assert sql == SPEECH_RESULTS_SQL
    assert params[:2] == [datetime(2026, 11, 4, 0), datetime(2026, 11, 4, 12)]


def test_a_succeeded_request_never_shows_an_error_even_when_its_log_carries_one() -> None:
    prisma: Final = _prisma([_row(error="a retry failed before the call succeeded")])

    with (
        patch("litellm.proxy.proxy_server.prisma_client", prisma),
        patch("litellm.proxy.proxy_server.llm_router", None),
    ):
        response: Final = _client(LitellmUserRoles.PROXY_ADMIN).get("/qos/speech/evaluations")

    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["error"] is None


def test_rating_a_reading_records_it_under_the_caller_and_returns_it() -> None:
    prisma: Final = _prisma([{"request_id": "call-1"}])
    before: Final = datetime.now(timezone.utc)

    with patch("litellm.proxy.proxy_server.prisma_client", prisma):
        response: Final = _client(LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY, user_id="admin-1").put(
            "/qos/speech/review?request_id=call-1", json={"overall": 5}
        )

    after: Final = datetime.now(timezone.utc)
    assert response.status_code == 200, response.text
    assert response.json()["overall"] == 5
    ((sql, request_id, reviewer, saved),) = (call.args for call in prisma.db.query_raw.await_args_list)
    assert (sql, request_id, reviewer) == (RECORD_SPEECH_REVIEW_SQL, "call-1", "admin-1")
    assert json.loads(saved)["overall"] == 5
    assert before.replace(microsecond=0) <= datetime.fromisoformat(json.loads(saved)["reviewed_at"]) <= after


@pytest.mark.parametrize("body", ({"overall": 0}, {"overall": 6}, {"overall": 3, "motion": 2}))
def test_a_reading_is_rated_from_1_to_5_overall_only(body: dict[str, int]) -> None:
    prisma: Final = _prisma([{"request_id": "call-1"}])

    with patch("litellm.proxy.proxy_server.prisma_client", prisma):
        response: Final = _client(LitellmUserRoles.PROXY_ADMIN).put("/qos/speech/review?request_id=call-1", json=body)

    assert response.status_code == 422
    prisma.db.query_raw.assert_not_awaited()


def test_rating_a_request_the_probe_did_not_make_is_not_found() -> None:
    with patch("litellm.proxy.proxy_server.prisma_client", _prisma([])):
        response: Final = _client(LitellmUserRoles.PROXY_ADMIN).put(
            "/qos/speech/review?request_id=someone-elses", json={"overall": 3}
        )

    assert response.status_code == 404


@pytest.mark.parametrize(("recorded", "status"), (([{"request_id": "call-3"}], 200), ([], 404)))
def test_a_transcript_is_kept_on_its_request_and_is_not_found_until_the_request_is_logged(
    recorded: list[dict[str, str]], status: int
) -> None:
    prisma: Final = _prisma(recorded)

    with patch("litellm.proxy.proxy_server.prisma_client", prisma):
        response: Final = _client(LitellmUserRoles.PROXY_ADMIN).put(
            "/qos/speech/evaluations/transcript?request_id=call-3", json={"text": "今天天气很好"}
        )

    assert response.status_code == status
    ((sql, request_id, transcript),) = (call.args for call in prisma.db.query_raw.await_args_list)
    assert (sql, request_id, json.loads(transcript)) == (RECORD_TRANSCRIPT_SQL, "call-3", {"text": "今天天气很好"})


def _deployment(name: str, mode: str, qos_probe: dict[str, object] | None) -> dict[str, object]:
    info: Final = {"mode": mode} if qos_probe is None else {"mode": mode, "qos_probe": qos_probe}
    return {"model_name": name, "litellm_params": {"model": f"moark/{name}"}, "model_info": info}


@pytest.mark.parametrize(("probe", "available"), ((_Probe().media_probe(), True), (None, False)))
def test_a_runs_options_list_each_probed_speech_and_transcription_model_once(
    probe: MediaProbe | None, available: bool
) -> None:
    llm_router: Final = MagicMock()
    llm_router.get_model_list = MagicMock(
        return_value=[
            _deployment("IndexTTS-2", "audio_speech", {"params": {"prompt_audio_url": "https://voice/a.wav"}}),
            _deployment("IndexTTS-2", "audio_speech", {}),
            _deployment("ChatTTS", "audio_speech", None),
            _deployment("SenseVoiceSmall", "audio_transcription", {}),
            _deployment("LTX-2", "video_generation", {"image": True}),
        ]
    )

    with patch("litellm.proxy.proxy_server.llm_router", llm_router):
        response: Final = _client(LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY, probe).get("/qos/speech/evaluations/options")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "available": available,
        "models": [
            {"model_group": "IndexTTS-2", "modality": "speech"},
            {"model_group": "SenseVoiceSmall", "modality": "transcription"},
        ],
    }


def test_starting_a_run_asks_the_probe_with_the_master_key_and_names_the_models_it_tests() -> None:
    probe: Final = _Probe(status=202, content=json.dumps({"models": ["IndexTTS-2", "SenseVoiceSmall"]}).encode())

    response: Final = _client(LitellmUserRoles.PROXY_ADMIN, probe.media_probe()).post("/qos/speech/evaluations")

    assert response.status_code == 200, response.text
    assert response.json() == {"models": ["IndexTTS-2", "SenseVoiceSmall"]}
    ((request,),) = (probe.requests,)
    assert (request.method, request.url.path, request.headers["authorization"]) == (
        "POST",
        "/speech-evaluations",
        "Bearer sk-master",
    )


def test_without_a_probe_a_run_cannot_start() -> None:
    response: Final = _client(LitellmUserRoles.PROXY_ADMIN).post("/qos/speech/evaluations")

    assert response.status_code == 503


@pytest.mark.parametrize(
    ("path", "probe_path"),
    (("/qos/speech/audio?request_id=call-1", "/audio/call-1"), ("/qos/speech/recording", "/recording")),
)
def test_audio_is_fetched_from_the_probe_and_served_as_the_type_the_probe_names(path: str, probe_path: str) -> None:
    probe: Final = _Probe(content=WAV, content_type="audio/wav")

    response: Final = _client(LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY, probe.media_probe()).get(path)

    assert response.status_code == 200, response.text
    assert (response.content, response.headers["content-type"]) == (WAV, "audio/wav")
    ((request,),) = (probe.requests,)
    assert (request.url.path, request.headers["authorization"]) == (probe_path, "Bearer sk-master")


def test_audio_the_probe_no_longer_has_is_not_found() -> None:
    probe: Final = _Probe(status=404, content=b"")

    response: Final = _client(LitellmUserRoles.PROXY_ADMIN, probe.media_probe()).get(
        "/qos/speech/audio?request_id=call-1"
    )

    assert response.status_code == 404


@pytest.mark.parametrize("request_id", ("../recording", "call 1", "a" * 129))
def test_an_audio_id_that_could_reach_another_file_is_refused_before_asking_the_probe(request_id: str) -> None:
    probe: Final = _Probe(content=WAV, content_type="audio/wav")

    response: Final = _client(LitellmUserRoles.PROXY_ADMIN, probe.media_probe()).get(
        "/qos/speech/audio", params={"request_id": request_id}
    )

    assert response.status_code == 422
    assert probe.requests == []
