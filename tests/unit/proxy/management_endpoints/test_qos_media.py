import io
import wave
from typing import Final

import httpx
import pytest

from litellm.proxy.management_endpoints.qos_media import qos_media, spoken_chars
from litellm.types.llms.openai import HttpxBinaryResponseContent
from litellm.types.qos import PROVIDER_TASK_HIDDEN_PARAM
from litellm.types.utils import TranscriptionResponse
from litellm.types.videos.main import VideoObject


def _wav(sample_rate: int, channels: int, frames: int) -> bytes:
    buffer: Final = io.BytesIO()
    with wave.open(buffer, "wb") as clip:
        clip.setnchannels(channels)
        clip.setsampwidth(2)
        clip.setframerate(sample_rate)
        clip.writeframes(b"\x00\x00" * channels * frames)
    return buffer.getvalue()


def _speech_reply(audio: bytes) -> HttpxBinaryResponseContent:
    return HttpxBinaryResponseContent(httpx.Response(200, content=audio))


@pytest.mark.parametrize(("text", "chars"), [("你好，世界！", 4), ("GPT-5 发布了。", 7), ("  \n", 0)])
def test_spoken_characters_leave_out_punctuation_and_spaces(text: str, chars: int) -> None:
    assert spoken_chars(text) == chars


def test_speech_records_the_wav_header_and_its_length_and_the_spoken_input() -> None:
    assert qos_media("aspeech", "你好，世界！", _speech_reply(_wav(22050, 1, 11025))) == {
        "input_chars": 4,
        "audio_seconds": 0.5,
        "sample_rate": 22050,
        "channels": 1,
        "format": "wav",
    }


def test_speech_length_counts_the_audio_actually_received_when_the_wav_header_overstates_it() -> None:
    whole: Final = _wav(16000, 2, 16000)
    truncated: Final = whole[: len(whole) - 2 * 2 * 8000]

    assert qos_media("speech", "好", _speech_reply(truncated)) == {
        "input_chars": 1,
        "audio_seconds": 0.5,
        "sample_rate": 16000,
        "channels": 2,
        "format": "wav",
    }


def test_mp3_speech_records_its_format_without_a_length() -> None:
    assert qos_media("aspeech", "好", _speech_reply(b"ID3\x04\x00" + b"\x00" * 64)) == {
        "input_chars": 1,
        "format": "mp3",
    }


def test_transcription_records_the_audio_length_litellm_measured() -> None:
    response: Final = TranscriptionResponse(text="你好")
    response.hidden_params = {"audio_transcription_duration": 3.25}

    assert qos_media("atranscription", None, response) == {"audio_seconds": 3.25}


@pytest.mark.parametrize("call_type", ["avideo_generation", "avideo_status"])
def test_a_video_task_records_queue_and_run_time_and_its_price(call_type: str) -> None:
    video: Final = VideoObject(id="video_1", object="video", status="completed")
    video.hidden_params = {
        PROVIDER_TASK_HIDDEN_PARAM: {
            "task_id": "TASK-1",
            "status": "success",
            "created_at": "2026-10-27T00:00:00Z",
            "started_at": "2026-10-27T00:00:05Z",
            "completed_at": "2026-10-27T00:01:05.500Z",
            "price": 0.9,
            "currency": "CNY",
        }
    }

    assert qos_media(call_type, None, video) == {
        "task_id": "TASK-1",
        "task_status": "success",
        "queue_ms": 5000.0,
        "run_ms": 60500.0,
        "task_price": 0.9,
        "task_currency": "CNY",
    }


def test_a_video_from_a_provider_without_task_details_records_nothing() -> None:
    assert qos_media("avideo_generation", None, VideoObject(id="video_1", object="video", status="queued")) is None


@pytest.mark.parametrize("call_type", ["acompletion", "aembedding", None])
def test_calls_that_are_not_audio_or_video_record_nothing(call_type: str | None) -> None:
    assert qos_media(call_type, "hi", _speech_reply(_wav(16000, 1, 160))) is None
