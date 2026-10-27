"""
Moark (Gitee AI) text-to-speech: https://ai.gitee.com/docs/products/apis/speeches/text-to-speech

Each Moark speech model takes its own body fields (IndexTTS-2 clones the voice in prompt_audio_url and has no
preset voices), so every caller field LiteLLM does not own is sent as is, and `voice` stays optional.
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

import httpx

from litellm.llms.base_llm.chat.transformation import BaseLLMException
from litellm.llms.base_llm.text_to_speech.transformation import BaseTextToSpeechConfig, TextToSpeechRequestData
from litellm.llms.moark.common_utils import MoarkError, moark_api_base, moark_auth_headers
from litellm.types.llms.openai import HttpxBinaryResponseContent
from litellm.utils import filter_out_litellm_params

if TYPE_CHECKING:
    from litellm.litellm_core_utils.litellm_logging import Logging as LiteLLMLoggingObj

_OPENAI_ONLY_PARAMS: Final = frozenset({"response_format", "instructions"})
_NOT_FORWARDED: Final = _OPENAI_ONLY_PARAMS | {
    "model",
    "input",
    "voice",
    "user",
    "extra_body",
    "extra_headers",
    "timeout",
    "stream",
}


def _forwarded(params: Mapping[str, object]) -> Mapping[str, object]:
    return {
        key: value
        for key, value in filter_out_litellm_params(params, excluding=_NOT_FORWARDED).items()
        if value is not None
    }


class MoarkTextToSpeechConfig(BaseTextToSpeechConfig):
    def get_supported_openai_params(self, model: str) -> list[str]:  # mutable-ok: mirrors override contract
        return ["voice", "speed"]

    def map_openai_params(
        self,
        model: str,
        optional_params: Mapping[str, object],
        voice: str | Mapping[str, object] | None = None,
        drop_params: bool = False,
        kwargs: Mapping[str, object] | None = None,
    ) -> tuple[str | None, dict[str, object]]:  # mutable-ok: main.speech passes the params on as a dict
        passed: Final = kwargs or {}
        extra_body: Final = passed.get("extra_body")
        return voice if isinstance(voice, str) else None, {
            **{key: value for key, value in optional_params.items() if key not in _OPENAI_ONLY_PARAMS},
            **_forwarded(passed),
            **(_forwarded(extra_body) if isinstance(extra_body, Mapping) else {}),
        }

    def validate_environment(
        self,
        headers: Mapping[str, str],
        model: str,
        api_key: str | None = None,
        api_base: str | None = None,
    ) -> dict[str, str]:  # mutable-ok: the handler adds extra headers to the dict it gets back
        return {**headers, **moark_auth_headers(api_key)}

    def get_complete_url(self, model: str, api_base: str | None, litellm_params: Mapping[str, object]) -> str:
        return f"{moark_api_base(api_base)}/audio/speech"

    def transform_text_to_speech_request(
        self,
        model: str,
        input: str,
        voice: str | None,
        optional_params: Mapping[str, object],
        litellm_params: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> TextToSpeechRequestData:
        return TextToSpeechRequestData(
            dict_body={
                **optional_params,
                **({} if voice is None else {"voice": voice}),
                "model": model,
                "input": input,
                "response_data_format": "blob",
            },
        )

    def transform_text_to_speech_response(
        self,
        model: str,
        raw_response: httpx.Response,
        logging_obj: "LiteLLMLoggingObj",
    ) -> HttpxBinaryResponseContent:
        if any(value.startswith("application/json") for value in raw_response.headers.get_list("content-type")):
            raise MoarkError(
                status_code=502,
                message=f"Moark returned JSON instead of audio: {raw_response.text[:500]}",
                headers=raw_response.headers,
            )
        return HttpxBinaryResponseContent(raw_response)

    def get_error_class(
        self,
        error_message: str,
        status_code: int,
        headers: dict[str, str] | httpx.Headers,  # mutable-ok: BaseLLMException takes headers as a dict
    ) -> BaseLLMException:
        return MoarkError(status_code=status_code, message=error_message, headers=headers)
