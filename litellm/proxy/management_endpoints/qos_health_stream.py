import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import Final

from pydantic import ConfigDict

import litellm
from litellm.constants import HEALTH_CHECK_TIMEOUT_SECONDS
from litellm.litellm_core_utils.health_check_helpers import HealthCheckHelpers
from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper
from litellm.proxy.health_check import resolve_health_check_mode, update_litellm_params_for_health_check
from litellm.router_utils.auto_router_model_naming import classify_strategy_router_model
from litellm.types.llms.base import LiteLLMBaseModel
from litellm.types.router import Deployment


class StreamHealthResult(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    ttft_ms: float | None
    latency_ms: float | None
    error: str | None


def supports_stream_probe(deployment: Deployment) -> bool:
    if classify_strategy_router_model(deployment.litellm_params.model) is not None:
        return False
    if "*" in deployment.litellm_params.model:
        return False
    mode: Final = resolve_health_check_mode(
        deployment.model_info.model_dump(exclude_none=True),
        deployment.litellm_params.model_dump(exclude_none=True),
    )
    return mode in (None, "chat")


async def _output_times(stream: CustomStreamWrapper, clock: Callable[[], float]) -> AsyncIterator[float]:
    async for chunk in stream:
        if any(choice.delta.get("content") or choice.delta.get("reasoning_content") for choice in chunk.choices):
            yield clock()


async def check_stream_health(
    deployment: Deployment, clock: Callable[[], float] = time.perf_counter
) -> StreamHealthResult:
    info: Final = deployment.model_info.model_dump(exclude_none=True)
    params: Final = update_litellm_params_for_health_check(
        info, deployment.litellm_params.model_dump(exclude_none=True)
    )
    tracked: Final = HealthCheckHelpers.update_model_params_with_health_check_tracking_information(params)
    timeout: Final = info.get("health_check_timeout", HEALTH_CHECK_TIMEOUT_SECONDS)
    started: Final = clock()
    try:
        async with asyncio.timeout(timeout):
            stream: Final = await litellm.acompletion(**{**tracked, "stream": True, "cache": {"no-cache": True}})
            if not isinstance(stream, CustomStreamWrapper):
                return StreamHealthResult(ttft_ms=None, latency_ms=None, error="Model did not return a stream")
            try:
                output: Final = _output_times(stream, clock)
                first: Final = await anext(output, None)
                async for _ in output:
                    pass
                ended: Final = clock()
                if first is None:
                    return StreamHealthResult(ttft_ms=None, latency_ms=None, error="Model returned no output tokens")
                return StreamHealthResult(
                    ttft_ms=(first - started) * 1000,
                    latency_ms=(ended - started) * 1000,
                    error=None,
                )
            finally:
                await stream.aclose()
    except TimeoutError:
        return StreamHealthResult(ttft_ms=None, latency_ms=None, error="Model health check timed out")
    except Exception as error:
        return StreamHealthResult(ttft_ms=None, latency_ms=None, error=str(error))
