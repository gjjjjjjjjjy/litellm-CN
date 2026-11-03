"""
Audio and video facts for service quality, stored on the request's own spend log row under `qos_media`: input
characters and output length of speech, audio length of a transcription, and queue and run time of a video task.
"""

import io
import unicodedata
import wave
from collections.abc import Mapping
from datetime import datetime
from typing import Final

from pydantic import JsonValue, TypeAdapter, ValidationError

from litellm.types.llms.openai import HttpxBinaryResponseContent
from litellm.types.qos import PROBE_PROMPT_MAX_CHARS, PROVIDER_TASK_HIDDEN_PARAM, QosMedia, QosProviderTask

QOS_MEDIA_KEY: Final = "qos_media"
SPEECH_CALL_TYPES: Final = frozenset({"speech", "aspeech"})
TRANSCRIPTION_CALL_TYPES: Final = frozenset({"transcription", "atranscription"})
VIDEO_CREATE_CALL_TYPES: Final = frozenset(
    {
        "create_video",
        "acreate_video",
        "video_generation",
        "avideo_generation",
        "video_remix",
        "avideo_remix",
        "video_edit",
        "avideo_edit",
        "video_extension",
        "avideo_extension",
    }
)
VIDEO_STATUS_CALL_TYPES: Final = frozenset({"video_status", "avideo_status", "video_retrieve", "avideo_retrieve"})
VIDEO_TASK_CALL_TYPES: Final = VIDEO_CREATE_CALL_TYPES | VIDEO_STATUS_CALL_TYPES
QOS_MEDIA_PROBE_TAG: Final = "qos-media-probe"
_UNSPOKEN_CATEGORIES: Final = ("P", "Z", "C")
_MP3_SYNC: Final = (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xfa")
_HIDDEN_PARAMS: Final = TypeAdapter(dict[str, object])
_TAG_LIST: Final = TypeAdapter(list[object])


def spoken_chars(text: str) -> int:
    """Characters a voice reads out: everything except punctuation, spaces and control characters."""
    return sum(1 for char in text if not unicodedata.category(char).startswith(_UNSPOKEN_CATEGORIES))


def _hidden_param(response: object, key: str) -> object:
    hidden: Final[object] = getattr(response, "_hidden_params", None)
    return _HIDDEN_PARAMS.validate_python(hidden).get(key) if isinstance(hidden, dict) else None


def _wav(audio: bytes) -> QosMedia | None:
    try:
        with wave.open(io.BytesIO(audio), "rb") as clip:
            frame_bytes: Final = clip.getsampwidth() * clip.getnchannels()
            frames: Final = len(clip.readframes(len(audio))) // frame_bytes
            return QosMedia(
                format="wav",
                sample_rate=clip.getframerate(),
                channels=clip.getnchannels(),
                audio_seconds=frames / clip.getframerate(),
            )
    except (wave.Error, EOFError, ZeroDivisionError):
        return None


def _audio(audio: bytes) -> QosMedia:
    if audio.startswith(b"RIFF"):
        return _wav(audio) or QosMedia(format="wav")
    if audio.startswith(_MP3_SYNC):
        return QosMedia(format="mp3")
    return QosMedia()


def _speech(request_input: object, response: object) -> QosMedia:
    audio: Final = _audio(response.content) if isinstance(response, HttpxBinaryResponseContent) else QosMedia()
    return audio.model_copy(
        update={"input_chars": spoken_chars(request_input) if isinstance(request_input, str) else None}
    )


def _transcription(response: object) -> QosMedia:
    duration: Final[object] = _hidden_param(response, "audio_transcription_duration") or getattr(
        response, "duration", None
    )
    return QosMedia(audio_seconds=float(duration) if isinstance(duration, int | float) else None)


def _milliseconds(start: datetime | None, end: datetime | None) -> float | None:
    return None if start is None or end is None else (end - start).total_seconds() * 1000


def _video(response: object) -> QosMedia | None:
    reported: Final = _hidden_param(response, PROVIDER_TASK_HIDDEN_PARAM)
    if not isinstance(reported, Mapping):
        return None
    task: Final = QosProviderTask.model_validate(reported)
    return QosMedia(
        task_id=task.task_id,
        task_status=task.status,
        queue_ms=_milliseconds(task.created_at, task.started_at),
        run_ms=_milliseconds(task.started_at, task.completed_at),
        task_price=task.price,
        task_currency=task.currency,
    )


def _media(call_type: object, request_input: object, response: object) -> QosMedia | None:
    if call_type in SPEECH_CALL_TYPES:
        return _speech(request_input, response)
    if call_type in TRANSCRIPTION_CALL_TYPES:
        return _transcription(response)
    if call_type in VIDEO_TASK_CALL_TYPES:
        return _video(response)
    return None


def tag_list(tags: object) -> tuple[object, ...] | None:
    """A request's tags when its metadata holds a list of them, or None for anything else."""
    try:
        return tuple(_TAG_LIST.validate_python(tags, strict=True))
    except ValidationError:
        return None


def _probe_prompt(call_type: object, request_input: object, tags: object) -> str | None:
    tagged: Final = isinstance(tags, list | tuple) and QOS_MEDIA_PROBE_TAG in tags
    if call_type in VIDEO_CREATE_CALL_TYPES and tagged and isinstance(request_input, str):
        return request_input[:PROBE_PROMPT_MAX_CHARS]
    return None


def qos_media(
    call_type: object, request_input: object, response: object, tags: object = None
) -> Mapping[str, JsonValue] | None:
    """The `qos_media` entry of a request's spend log metadata, or None for calls it does not describe.

    Only a video created by the scheduled probe (tagged `qos-media-probe`) keeps its prompt, for reviewers to judge
    how well the video follows it; other prompts are not stored.
    """
    media: Final = _media(call_type, request_input, response)
    if media is None:
        return None
    prompt: Final = _probe_prompt(call_type, request_input, tags)
    described: Final = media if prompt is None else media.model_copy(update={"prompt": prompt})
    return described.model_dump(mode="json", exclude_none=True)
