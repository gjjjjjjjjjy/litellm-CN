"""
The media probe's API, which only the gateway can reach: the gateway starts evaluation runs on it and fetches the
audio it keeps, authenticated with the master key. QOS_MEDIA_PROBE_URL names it.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, TypeVar

import httpx
from fastapi import HTTPException
from pydantic import ConfigDict, JsonValue, TypeAdapter, ValidationError

from litellm.types.llms.base import LiteLLMBaseModel

MEDIA_PROBE_URL_ENV: Final = "QOS_MEDIA_PROBE_URL"
_Answer = TypeVar("_Answer", bound=LiteLLMBaseModel)


@dataclass(frozen=True, slots=True)
class MediaProbe:
    base_url: str
    token: str
    transport: httpx.AsyncBaseTransport | None = None

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            transport=self.transport,
            timeout=timeout,
            headers={"Authorization": f"Bearer {self.token}"},
        )

    async def post(self, path: str, body: Mapping[str, JsonValue], timeout: float) -> httpx.Response:
        async with self._client(timeout) as client:
            return await client.post(path, json=body)

    async def get(self, path: str, timeout: float) -> httpx.Response:
        async with self._client(timeout) as client:
            return await client.get(path)


def media_probe() -> MediaProbe | None:
    from litellm.proxy.proxy_server import master_key

    url: Final = os.environ.get(MEDIA_PROBE_URL_ENV, "").strip().rstrip("/")
    return MediaProbe(base_url=url, token=master_key) if url and master_key else None


def _no_probe() -> HTTPException:
    return HTTPException(status_code=503, detail=f"No media probe is set up; set {MEDIA_PROBE_URL_ENV} on the gateway")


async def ask_probe(probe: MediaProbe | None, path: str, body: Mapping[str, JsonValue], timeout: float) -> bytes:
    if probe is None:
        raise _no_probe()
    try:
        response: Final = await probe.post(path, body, timeout)
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail=f"Could not reach the media probe: {error!r}") from error
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"The media probe answered {response.status_code}: {response.text[:300]}"
        )
    return response.content


async def fetch_from_probe(probe: MediaProbe | None, path: str, timeout: float) -> httpx.Response:
    """A file the probe keeps; a 404 stays a 404 so the caller can say the file is gone."""
    if probe is None:
        raise _no_probe()
    try:
        response: Final = await probe.get(path, timeout)
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail=f"Could not reach the media probe: {error!r}") from error
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="The media probe no longer has this audio")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"The media probe answered {response.status_code}")
    return response


def probe_answer(answer: type[_Answer], content: bytes) -> _Answer:
    try:
        return answer.model_validate_json(content)
    except ValidationError as error:
        raise HTTPException(status_code=502, detail=f"The media probe's answer is not readable: {error}") from error


class ProbeSpec(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    image: bool = False


class ProbedModelInfo(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    mode: str | None = None
    qos_probe: ProbeSpec | None = None


class ProbedDeployment(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    model_name: str
    model_info: ProbedModelInfo = ProbedModelInfo()


DEPLOYMENTS: Final = TypeAdapter(tuple[ProbedDeployment, ...])


def first_of_each(deployments: tuple[ProbedDeployment, ...]) -> tuple[ProbedDeployment, ...]:
    names: Final = tuple(deployment.model_name for deployment in deployments)
    return tuple(
        deployment for index, deployment in enumerate(deployments) if deployment.model_name not in names[:index]
    )


def listed_deployments() -> tuple[ProbedDeployment, ...]:
    from litellm.proxy.proxy_server import llm_router

    return DEPLOYMENTS.validate_python((llm_router.get_model_list() if llm_router else None) or ())
