import io
import json
from datetime import datetime, timezone
from typing import Final
from unittest.mock import Mock

import httpx
import pytest
import respx

import litellm
from litellm.llms.moark.common_utils import MoarkError
from litellm.llms.moark.videos.transformation import MoarkVideoConfig
from litellm.llms.openai_like.json_loader import JSONProviderRegistry
from litellm.types.qos import PROVIDER_TASK_HIDDEN_PARAM
from litellm.types.router import GenericLiteLLMParams
from litellm.types.videos.utils import decode_video_id_with_provider

_REGISTRY: Final = JSONProviderRegistry.get("moark")
assert _REGISTRY is not None
_BASE: Final = _REGISTRY.base_url
_CREATED: Final = "2026-10-27T08:00:00+08:00"


def _task(status: str, **fields: object) -> dict[str, object]:
    return {
        "task_id": "TASK-1",
        "status": status,
        "created_at": _CREATED,
        "urls": {"get": f"{_BASE}/task/TASK-1", "cancel": f"{_BASE}/task/TASK-1/cancel"},
        **fields,
    }


@respx.mock
def test_an_image_url_goes_to_image_to_video_with_the_model_fields_unchanged() -> None:
    route: Final = respx.post(f"{_BASE}/async/videos/image-to-video").mock(
        return_value=httpx.Response(200, json=_task("waiting"))
    )

    video: Final = litellm.video_generation(
        model="moark/LTX-2",
        prompt="猫在弹钢琴",
        input_reference="https://cdn.example.com/cat.png",
        seed=7,
        num_frames=25,
        api_key="moark-test-key",
    )

    request: Final = route.calls.last.request
    assert request.headers["authorization"] == "Bearer moark-test-key"
    assert json.loads(request.content) == {
        "model": "LTX-2",
        "prompt": "猫在弹钢琴",
        "image_url": "https://cdn.example.com/cat.png",
        "seed": 7,
        "num_frames": 25,
    }
    assert (video.status, video.created_at) == ("queued", int(datetime.fromisoformat(_CREATED).timestamp()))
    assert decode_video_id_with_provider(video.id) == {
        "custom_llm_provider": "moark",
        "model_id": "LTX-2",
        "video_id": "TASK-1",
    }


@respx.mock
def test_a_prompt_alone_goes_to_text_to_video_with_seconds_as_duration_and_size_as_dimensions() -> None:
    route: Final = respx.post(f"{_BASE}/async/videos/generations").mock(
        return_value=httpx.Response(200, json=_task("waiting"))
    )

    litellm.video_generation(
        model="moark/MiniMax-H3",
        prompt="海边日落",
        seconds="4",
        size="1280x720",
        task="t2va",
        api_key="moark-test-key",
    )

    assert json.loads(route.calls.last.request.content) == {
        "model": "MiniMax-H3",
        "prompt": "海边日落",
        "duration_seconds": 4,
        "width": 1280,
        "height": 720,
        "task": "t2va",
    }


def test_an_uploaded_image_is_sent_as_a_multipart_file_with_the_other_fields_as_form_values() -> None:
    image: Final = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    data, files, url = MoarkVideoConfig().transform_video_create_request(
        model="Wan2_2-I2V-A14B",
        prompt="风吹麦浪",
        api_base=_BASE,
        video_create_optional_request_params={"input_reference": image, "seed": 7, "num_frames": 33},
        litellm_params=GenericLiteLLMParams(),
        headers={},
    )

    assert url == f"{_BASE}/async/videos/image-to-video"
    assert data == {"model": "Wan2_2-I2V-A14B", "prompt": "风吹麦浪", "seed": "7", "num_frames": "33"}
    assert files == [("image", ("image.png", image, "image/png"))]


@pytest.mark.parametrize(
    ("moark_status", "video_status", "error"),
    [
        ("waiting", "queued", None),
        ("in_progress", "in_progress", None),
        ("success", "completed", None),
        ("failure", "failed", {"code": "failure", "message": "Moark task failure"}),
        ("cancelled", "failed", {"code": "cancelled", "message": "Moark task cancelled"}),
    ],
)
def test_every_moark_task_status_maps_to_a_video_status(
    moark_status: str, video_status: str, error: dict[str, str] | None
) -> None:
    video: Final = MoarkVideoConfig().transform_video_status_retrieve_response(
        raw_response=httpx.Response(200, json=_task(moark_status)), logging_obj=Mock(), custom_llm_provider="moark"
    )

    assert (video.status, video.error) == (video_status, error)


def test_a_finished_task_keeps_the_provider_timestamps_and_price_for_service_quality() -> None:
    video: Final = MoarkVideoConfig().transform_video_status_retrieve_response(
        raw_response=httpx.Response(
            200,
            json=_task(
                "success",
                started_at="2026-10-27T08:00:05+08:00",
                completed_at="2026-10-27T08:01:05+08:00",
                price=0.9,
                currency="CNY",
                output={"file_url": "https://cdn.example.com/out.mp4"},
            ),
        ),
        logging_obj=Mock(),
        custom_llm_provider="moark",
    )

    assert video.completed_at == int(datetime(2026, 10, 27, 0, 1, 5, tzinfo=timezone.utc).timestamp())
    assert video.hidden_params[PROVIDER_TASK_HIDDEN_PARAM] == {
        "task_id": "TASK-1",
        "status": "success",
        "created_at": "2026-10-27T00:00:00Z",
        "started_at": "2026-10-27T00:00:05Z",
        "completed_at": "2026-10-27T00:01:05Z",
        "price": 0.9,
        "currency": "CNY",
    }


@respx.mock
def test_status_of_a_created_video_polls_its_moark_task() -> None:
    respx.post(f"{_BASE}/async/videos/generations").mock(return_value=httpx.Response(200, json=_task("waiting")))
    poll: Final = respx.get(f"{_BASE}/task/TASK-1").mock(return_value=httpx.Response(200, json=_task("in_progress")))

    created: Final = litellm.video_generation(model="moark/MiniMax-H3", prompt="海边日落", api_key="moark-test-key")
    status: Final = litellm.video_status(video_id=created.id, custom_llm_provider="moark", api_key="moark-test-key")

    assert poll.calls.last.request.headers["authorization"] == "Bearer moark-test-key"
    assert status.status == "in_progress"


@pytest.mark.asyncio
async def test_the_video_is_downloaded_from_its_file_url_without_the_moark_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(litellm, "disable_aiohttp_transport", True)
    with respx.mock(assert_all_called=True) as mock:
        download: Final = mock.get("https://cdn.example.com/out.mp4").mock(
            return_value=httpx.Response(200, content=b"mp4-bytes")
        )

        content: Final = await MoarkVideoConfig().async_transform_video_content_response(
            raw_response=httpx.Response(
                200, json=_task("success", output={"file_url": "https://cdn.example.com/out.mp4"})
            ),
            logging_obj=Mock(),
        )

    assert content == b"mp4-bytes"
    assert "authorization" not in download.calls.last.request.headers


def test_asking_for_the_video_of_an_unfinished_task_is_an_error() -> None:
    with pytest.raises(MoarkError, match="has no video yet"):
        MoarkVideoConfig().transform_video_content_response(
            raw_response=httpx.Response(200, json=_task("in_progress")), logging_obj=Mock()
        )
