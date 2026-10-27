import json
from typing import Final

import httpx
import pytest
import respx

import litellm
from litellm.llms.openai_like.json_loader import JSONProviderRegistry

_REGISTRY: Final = JSONProviderRegistry.get("moark")
assert _REGISTRY is not None
_SPEECH_URL: Final = f"{_REGISTRY.base_url}/audio/speech"
_AUDIO: Final = b"RIFF\x24\x00\x00\x00WAVEfmt "


def _audio_reply() -> httpx.Response:
    return httpx.Response(200, content=_AUDIO, headers={"content-type": "audio/wav"})


@respx.mock
def test_index_tts_sends_its_voice_clone_fields_and_needs_no_preset_voice() -> None:
    route: Final = respx.post(_SPEECH_URL).mock(return_value=_audio_reply())

    response: Final = litellm.speech(
        model="moark/IndexTTS-2",
        input="今天天气不错",
        prompt_audio_url="https://cdn.example.com/reference.wav",
        prompt_text="参考音频里说的话",
        emo_text="开心",
        api_key="moark-test-key",
    )

    request: Final = route.calls.last.request
    assert request.headers["authorization"] == "Bearer moark-test-key"
    assert json.loads(request.content) == {
        "model": "IndexTTS-2",
        "input": "今天天气不错",
        "prompt_audio_url": "https://cdn.example.com/reference.wav",
        "prompt_text": "参考音频里说的话",
        "emo_text": "开心",
        "response_data_format": "blob",
    }
    assert response.content == _AUDIO


@respx.mock
def test_a_preset_voice_and_extra_body_fields_are_sent_but_cannot_replace_the_model_or_audio_format() -> None:
    route: Final = respx.post(_SPEECH_URL).mock(return_value=_audio_reply())

    litellm.speech(
        model="moark/TeleTTS-Mandarin",
        input="你好",
        voice="中文女",
        response_format="mp3",
        extra_body={"volume": 1.5, "model": "another-model", "response_data_format": "url"},
        api_key="moark-test-key",
    )

    assert json.loads(route.calls.last.request.content) == {
        "model": "TeleTTS-Mandarin",
        "input": "你好",
        "voice": "中文女",
        "volume": 1.5,
        "response_data_format": "blob",
    }


@respx.mock
def test_the_key_falls_back_to_moark_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_REGISTRY.api_key_env, "key-from-env")
    route: Final = respx.post(_SPEECH_URL).mock(return_value=_audio_reply())

    litellm.speech(model="moark/IndexTTS-2", input="你好", prompt_audio_url="https://cdn.example.com/r.wav")

    assert route.calls.last.request.headers["authorization"] == "Bearer key-from-env"


@pytest.mark.asyncio
async def test_a_json_reply_reaches_the_caller_as_a_bad_gateway_instead_of_as_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(litellm, "disable_aiohttp_transport", True)
    with respx.mock(assert_all_called=True) as mock:
        mock.post(_SPEECH_URL).mock(
            return_value=httpx.Response(200, json={"url": "https://cdn.example.com/out.wav", "format": "wav"})
        )

        with pytest.raises(litellm.exceptions.BadGatewayError, match="Moark returned JSON instead of audio"):
            await litellm.aspeech(
                model="moark/IndexTTS-2",
                input="你好",
                prompt_audio_url="https://cdn.example.com/r.wav",
                api_key="moark-test-key",
            )
