from collections.abc import AsyncIterator
from typing import Final
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper
from litellm.proxy.management_endpoints.qos_health_stream import check_stream_health, supports_stream_probe
from litellm.types.router import Deployment
from litellm.types.utils import ModelResponseStream


def _deployment(mode: str = "chat") -> Deployment:
    return Deployment(
        model_name="shared-model",
        litellm_params={"model": "openai/test-model", "api_base": "https://node.example/v1"},
        model_info={"id": "node-a", "mode": mode, "health_check_max_tokens": 32},
    )


def _stream(chunks: list[ModelResponseStream]) -> MagicMock:
    stream: Final = MagicMock(spec=CustomStreamWrapper)
    stream.__aiter__.return_value = chunks
    stream.aclose = AsyncMock()
    return stream


async def test_ttft_starts_at_output_including_reasoning_and_the_whole_stream_is_consumed() -> None:
    chunks: Final = [
        ModelResponseStream(choices=[{"delta": {"role": "assistant", "content": ""}}]),
        ModelResponseStream(choices=[{"delta": {"reasoning_content": "Thinking"}}]),
        ModelResponseStream(choices=[{"delta": {"content": "OK"}}]),
    ]
    stream: Final = _stream(chunks)
    ticks: Final = iter((10.0, 10.2, 10.5, 11.0))
    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=stream) as call:
        result: Final = await check_stream_health(_deployment(), lambda: next(ticks))
    assert result.error is None
    assert result.ttft_ms == pytest.approx(200)
    assert result.latency_ms == pytest.approx(1000)
    assert call.call_args.kwargs["stream"] is True
    assert call.call_args.kwargs["cache"] == {"no-cache": True}
    assert call.call_args.kwargs["max_tokens"] == 32
    assert call.call_args.kwargs["api_base"] == "https://node.example/v1"
    stream.aclose.assert_awaited_once()


async def test_empty_stream_is_a_failed_check_with_unknown_metrics() -> None:
    stream: Final = _stream([ModelResponseStream(choices=[{"delta": {"role": "assistant"}}])])
    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=stream):
        result: Final = await check_stream_health(_deployment(), lambda: 10.0)
    assert result.error == "Model returned no output tokens"
    assert (result.ttft_ms, result.latency_ms) == (None, None)
    stream.aclose.assert_awaited_once()


async def test_interrupted_stream_is_a_failed_check_and_is_closed() -> None:
    async def interrupted() -> AsyncIterator[ModelResponseStream]:
        yield ModelResponseStream(choices=[{"delta": {"content": "Partial"}}])
        raise ConnectionError("Upstream disconnected")

    stream: Final = _stream([])
    stream.__aiter__.side_effect = interrupted
    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=stream):
        result: Final = await check_stream_health(_deployment(), lambda: 10.0)
    assert result.error == "Upstream disconnected"
    assert (result.ttft_ms, result.latency_ms) == (None, None)
    stream.aclose.assert_awaited_once()


async def test_timeout_is_reported_as_a_failed_check_with_unknown_metrics() -> None:
    with patch("litellm.acompletion", new_callable=AsyncMock, side_effect=TimeoutError):
        result: Final = await check_stream_health(_deployment(), lambda: 10.0)
    assert result.error == "Model health check timed out"
    assert (result.ttft_ms, result.latency_ms) == (None, None)


@pytest.mark.parametrize("mode", ["audio_speech", "audio_transcription", "image_generation", "embedding"])
def test_other_modalities_keep_the_existing_health_check(mode: str) -> None:
    assert supports_stream_probe(_deployment(mode)) is False
