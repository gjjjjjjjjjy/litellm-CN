"""
Moark (Gitee AI) video generation on its asynchronous task API: https://ai.gitee.com/docs/products/apis/async-task

A request with an input image goes to image-to-video (LTX-2, Wan2_2-I2V-A14B), anything else to generations
(MiniMax-H3). Model-specific fields such as seed, num_frames or task are sent unchanged.
"""

import io
import json
from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import httpx
from httpx._types import FileTypes, RequestFiles
from pydantic import ConfigDict

from litellm.images.utils import ImageEditRequestUtils
from litellm.litellm_core_utils.url_utils import encode_url_path_segment
from litellm.llms.base_llm.chat.transformation import BaseLLMException
from litellm.llms.base_llm.videos.transformation import BaseVideoConfig
from litellm.llms.moark.common_utils import MoarkError, moark_api_base, moark_auth_headers
from litellm.types.qos import PROVIDER_TASK_HIDDEN_PARAM, QosProviderTask
from litellm.types.router import GenericLiteLLMParams
from litellm.types.videos.main import VideoCreateOptionalRequestParams, VideoObject
from litellm.types.videos.utils import encode_video_id_with_provider, extract_original_video_id

if TYPE_CHECKING:
    from litellm.litellm_core_utils.litellm_logging import Logging as LiteLLMLoggingObj
    from litellm.llms.custom_httpx.http_handler import HTTPHandler

DOWNLOAD_TIMEOUT_SECONDS: Final = 300.0
_VIDEO_STATUS: Final = MappingProxyType(
    {
        "waiting": "queued",
        "in_progress": "in_progress",
        "success": "completed",
        "failure": "failed",
        "cancelled": "failed",
    }
)
_ENDED_UNSUCCESSFULLY: Final = frozenset({"failure", "cancelled"})
_NOT_SENT: Final = frozenset({"model", "user", "extra_headers", "extra_body", "seconds", "size"})


class MoarkTask(QosProviderTask):
    model_config = ConfigDict(frozen=True, extra="ignore")

    output: Mapping[str, object] | None = None


def _task(raw_response: httpx.Response) -> MoarkTask:
    return MoarkTask.model_validate_json(raw_response.content)


def _task_path(video_id: str) -> str:
    return encode_url_path_segment(extract_original_video_id(video_id), field_name="video_id")


def _unix(moment: datetime | None) -> int | None:
    return None if moment is None else int(moment.timestamp())


def _size_fields(size: object) -> Mapping[str, int]:
    width, _, height = str(size).partition("x")
    return {"width": int(width), "height": int(height)} if width.isdigit() and height.isdigit() else {}


def _duration_field(seconds: object) -> Mapping[str, object]:
    if seconds is None:
        return {}
    return {"duration_seconds": int(seconds) if isinstance(seconds, str) and seconds.isdigit() else seconds}


def _form_value(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def _image_file(image: object) -> FileTypes:
    """An uploaded input_reference, sent as a named part with its content type; Moark reads the type from it."""
    if not isinstance(image, bytes | io.BytesIO | io.BufferedReader):
        raise MoarkError(status_code=400, message="input_reference must be image bytes, a binary file or an image URL")
    content_type: Final = ImageEditRequestUtils.get_image_content_type(image)
    return f"image.{content_type.rpartition('/')[2]}", image, content_type


def _file_url(task: MoarkTask) -> str:
    file_url: Final = None if task.output is None else task.output.get("file_url")
    if not isinstance(file_url, str):
        raise MoarkError(status_code=409, message=f"Moark task {task.task_id} has no video yet (status {task.status})")
    return file_url


def _downloaded(response: httpx.Response) -> bytes:
    response.raise_for_status()
    return response.content


def _video_object(task: MoarkTask, model: str | None, custom_llm_provider: str | None) -> VideoObject:
    ended_unsuccessfully: Final = task.status in _ENDED_UNSUCCESSFULLY
    video: Final = VideoObject(
        id=encode_video_id_with_provider(task.task_id, custom_llm_provider or "", model),
        object="video",
        status=_VIDEO_STATUS.get(task.status, "queued"),
        created_at=_unix(task.created_at),
        completed_at=_unix(task.completed_at),
        model=model,
        error={"code": task.status, "message": f"Moark task {task.status}"} if ended_unsuccessfully else None,
    )
    video.hidden_params = {
        **video.hidden_params,
        PROVIDER_TASK_HIDDEN_PARAM: task.model_dump(mode="json", exclude={"output"}),
    }
    return video


class MoarkVideoConfig(BaseVideoConfig):
    def get_supported_openai_params(self, model: str) -> list[str]:  # mutable-ok: mirrors override contract
        return ["input_reference", "seconds", "size", "user", "extra_headers"]

    def map_openai_params(
        self,
        video_create_optional_params: VideoCreateOptionalRequestParams,
        model: str,
        drop_params: bool,
    ) -> dict[str, object]:  # mutable-ok: the caller merges extra_body into the dict it gets back
        return {
            **{key: value for key, value in video_create_optional_params.items() if key not in _NOT_SENT},
            **_duration_field(video_create_optional_params.get("seconds")),
            **_size_fields(video_create_optional_params.get("size")),
        }

    def validate_environment(
        self,
        headers: Mapping[str, str],
        model: str,
        api_key: str | None = None,
        litellm_params: GenericLiteLLMParams | None = None,
    ) -> dict[str, str]:  # mutable-ok: the handler adds extra headers to the dict it gets back
        return {**headers, **moark_auth_headers(api_key or (litellm_params.api_key if litellm_params else None))}

    def get_complete_url(self, model: str, api_base: str | None, litellm_params: Mapping[str, object]) -> str:
        return moark_api_base(api_base)

    def transform_video_create_request(
        self,
        model: str,
        prompt: str,
        api_base: str,
        video_create_optional_request_params: Mapping[str, object],
        litellm_params: GenericLiteLLMParams,
        headers: Mapping[str, str],
    ) -> tuple[dict[str, object], RequestFiles, str]:  # mutable-ok: mirrors override contract
        image: Final = video_create_optional_request_params.get("input_reference")
        fields: Final = {
            "model": model,
            "prompt": prompt,
            **{key: value for key, value in video_create_optional_request_params.items() if key != "input_reference"},
        }
        if image is None:
            endpoint: Final = "image-to-video" if "image_url" in fields else "generations"
            return fields, [], f"{api_base}/async/videos/{endpoint}"
        if isinstance(image, str):
            return {**fields, "image_url": image}, [], f"{api_base}/async/videos/image-to-video"
        return (
            {key: _form_value(value) for key, value in fields.items()},
            [("image", _image_file(image))],
            f"{api_base}/async/videos/image-to-video",
        )

    def transform_video_create_response(
        self,
        model: str,
        raw_response: httpx.Response,
        logging_obj: "LiteLLMLoggingObj",
        custom_llm_provider: str | None = None,
        request_data: Mapping[str, object] | None = None,
    ) -> VideoObject:
        return _video_object(_task(raw_response), model, custom_llm_provider)

    def transform_video_status_retrieve_request(
        self,
        video_id: str,
        api_base: str,
        litellm_params: GenericLiteLLMParams,
        headers: Mapping[str, str],
    ) -> tuple[str, dict[str, object]]:  # mutable-ok: mirrors override contract
        return f"{api_base}/task/{_task_path(video_id)}", {}

    def transform_video_status_retrieve_response(
        self,
        raw_response: httpx.Response,
        logging_obj: "LiteLLMLoggingObj",
        custom_llm_provider: str | None = None,
        client: "HTTPHandler | None" = None,
    ) -> VideoObject:
        return _video_object(_task(raw_response), None, custom_llm_provider)

    def transform_video_content_request(
        self,
        video_id: str,
        api_base: str,
        litellm_params: GenericLiteLLMParams,
        headers: Mapping[str, str],
        variant: str | None = None,
    ) -> tuple[str, dict[str, object]]:  # mutable-ok: mirrors override contract
        return f"{api_base}/task/{_task_path(video_id)}", {}

    def transform_video_content_response(self, raw_response: httpx.Response, logging_obj: "LiteLLMLoggingObj") -> bytes:
        file_url: Final = _file_url(_task(raw_response))
        return _downloaded(httpx.get(file_url, timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True))

    async def async_transform_video_content_response(
        self,
        raw_response: httpx.Response,
        logging_obj: "LiteLLMLoggingObj",
    ) -> bytes:
        file_url: Final = _file_url(_task(raw_response))
        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
            return _downloaded(await client.get(file_url))

    def transform_video_remix_request(
        self,
        video_id: str,
        prompt: str,
        api_base: str,
        litellm_params: GenericLiteLLMParams,
        headers: Mapping[str, str],
        extra_body: Mapping[str, object] | None = None,
    ) -> tuple[str, dict[str, object]]:  # mutable-ok: mirrors override contract
        raise NotImplementedError("Moark has no video remix")

    def transform_video_remix_response(
        self,
        raw_response: httpx.Response,
        logging_obj: "LiteLLMLoggingObj",
        custom_llm_provider: str | None = None,
    ) -> VideoObject:
        raise NotImplementedError("Moark has no video remix")

    def transform_video_list_request(
        self,
        api_base: str,
        litellm_params: GenericLiteLLMParams,
        headers: Mapping[str, str],
        after: str | None = None,
        limit: int | None = None,
        order: str | None = None,
        extra_query: Mapping[str, object] | None = None,
    ) -> tuple[str, dict[str, object]]:  # mutable-ok: mirrors override contract
        raise NotImplementedError("Moark has no video list")

    def transform_video_list_response(
        self,
        raw_response: httpx.Response,
        logging_obj: "LiteLLMLoggingObj",
        custom_llm_provider: str | None = None,
    ) -> dict[str, str]:  # mutable-ok: mirrors override contract
        raise NotImplementedError("Moark has no video list")

    def transform_video_delete_request(
        self,
        video_id: str,
        api_base: str,
        litellm_params: GenericLiteLLMParams,
        headers: Mapping[str, str],
    ) -> tuple[str, dict[str, object]]:  # mutable-ok: mirrors override contract
        raise NotImplementedError("Moark cancels a task with POST /task/{id}/cancel; the videos DELETE route can't")

    def transform_video_delete_response(
        self, raw_response: httpx.Response, logging_obj: "LiteLLMLoggingObj"
    ) -> VideoObject:
        raise NotImplementedError("Moark cancels a task with POST /task/{id}/cancel; the videos DELETE route can't")

    def get_error_class(
        self,
        error_message: str,
        status_code: int,
        headers: dict[str, str] | httpx.Headers,  # mutable-ok: BaseLLMException takes headers as a dict
    ) -> BaseLLMException:
        return MoarkError(status_code=status_code, message=error_message, headers=headers)
