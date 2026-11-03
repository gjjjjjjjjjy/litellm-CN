"""
Evaluation runs started from the video review tab. The media probe generates a prompt's videos on every video model
it probes and has a vision model rate each one from a still per second, exactly as on its schedule.

The gateway forwards a run to the probe named by QOS_MEDIA_PROBE_URL and keeps the ratings the probe sends back:
generating a run takes hours and rating needs video decoding, both of which belong in the probe's own container.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import Annotated, Final, TypeVar

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ConfigDict, JsonValue, TypeAdapter, ValidationError

from litellm.proxy._types import CommonProxyErrors, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.management_endpoints.qos_access import require_admin, require_video_reviewer
from litellm.proxy.management_endpoints.qos_media import QOS_MEDIA_KEY, VIDEO_STATUS_CALL_TYPES
from litellm.proxy.management_endpoints.qos_sql import sql_list
from litellm.proxy.management_endpoints.qos_summary import QOS_MAX_WINDOW, as_utc_naive, query_rows, utc_now
from litellm.proxy.management_endpoints.qos_video_reviews import (
    CREATED,
    PROBE_MADE,
    RECORD_AI_REVIEW_SQL,
    RECORDED_REVIEW_ROWS,
)
from litellm.types.llms.base import LiteLLMBaseModel
from litellm.types.qos import (
    QosProbeModel,
    QosUsedPrompt,
    QosVideoAiReview,
    QosVideoAiScore,
    QosVideoEvaluationOptions,
    QosVideoEvaluationPrompt,
    QosVideoEvaluationRequest,
    QosVideoEvaluationStarted,
)

router: Final = APIRouter()

MEDIA_PROBE_URL_ENV: Final = "QOS_MEDIA_PROBE_URL"
USED_PROMPT_LIMIT: Final = 20
AVOIDED_PROMPTS: Final = 10
PRICE_WINDOW: Final = timedelta(days=7)
PROMPT_TIMEOUT_SECONDS: Final = 180.0
START_TIMEOUT_SECONDS: Final = 30.0

USED_PROMPTS_SQL: Final = f"""
SELECT metadata -> '{QOS_MEDIA_KEY}' ->> 'prompt' AS prompt, MAX("startTime") AS last_used, COUNT(*)::int AS videos
FROM "LiteLLM_SpendLogs"
WHERE "startTime" >= $1::timestamp AND call_type IN ({CREATED}) AND {PROBE_MADE}
GROUP BY 1
ORDER BY last_used DESC
LIMIT {USED_PROMPT_LIMIT}
"""

LATEST_PRICES_SQL: Final = f"""
SELECT DISTINCT ON (COALESCE(model_group, '')) COALESCE(model_group, '') AS model_group,
    (metadata -> '{QOS_MEDIA_KEY}' ->> 'task_price')::float AS last_price,
    metadata -> '{QOS_MEDIA_KEY}' ->> 'task_currency' AS currency
FROM "LiteLLM_SpendLogs"
WHERE "startTime" >= $1::timestamp
    AND call_type IN ({sql_list(VIDEO_STATUS_CALL_TYPES)})
    AND metadata -> '{QOS_MEDIA_KEY}' ->> 'task_price' IS NOT NULL
ORDER BY COALESCE(model_group, ''), "startTime" DESC
"""


class LatestPrice(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_group: str
    last_price: float
    currency: str | None


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


USED_PROMPT_ROWS: Final = TypeAdapter(tuple[QosUsedPrompt, ...])
LATEST_PRICE_ROWS: Final = TypeAdapter(tuple[LatestPrice, ...])
DEPLOYMENTS: Final = TypeAdapter(tuple[ProbedDeployment, ...])
_Answer = TypeVar("_Answer", bound=LiteLLMBaseModel)


@dataclass(frozen=True, slots=True)
class MediaProbe:
    """The probe's run API, which only the gateway can reach."""

    base_url: str
    token: str
    transport: httpx.AsyncBaseTransport | None = None

    async def post(self, path: str, body: Mapping[str, JsonValue], timeout: float) -> httpx.Response:
        async with httpx.AsyncClient(base_url=self.base_url, transport=self.transport, timeout=timeout) as client:
            return await client.post(path, json=body, headers={"Authorization": f"Bearer {self.token}"})


def media_probe() -> MediaProbe | None:
    from litellm.proxy.proxy_server import master_key

    url: Final = os.environ.get(MEDIA_PROBE_URL_ENV, "").strip().rstrip("/")
    return MediaProbe(base_url=url, token=master_key) if url and master_key else None


def _first_of_each(deployments: tuple[ProbedDeployment, ...]) -> tuple[ProbedDeployment, ...]:
    names: Final = tuple(deployment.model_name for deployment in deployments)
    return tuple(
        deployment for index, deployment in enumerate(deployments) if deployment.model_name not in names[:index]
    )


def _probe_model(name: str, spec: ProbeSpec, price: LatestPrice | None) -> QosProbeModel:
    return QosProbeModel(
        model_group=name,
        image_to_video=spec.image,
        last_price=None if price is None else price.last_price,
        currency=None if price is None else price.currency,
    )


def probe_models(
    deployments: tuple[ProbedDeployment, ...], prices: tuple[LatestPrice, ...]
) -> tuple[QosProbeModel, ...]:
    price_of: Final = MappingProxyType({price.model_group: price for price in prices})
    probed: Final = tuple(
        (deployment.model_name, deployment.model_info.qos_probe)
        for deployment in _first_of_each(deployments)
        if deployment.model_info.mode == "video_generation"
    )
    return tuple(_probe_model(name, spec, price_of.get(name)) for name, spec in probed if spec is not None)


async def _ask_probe(probe: MediaProbe | None, path: str, body: Mapping[str, JsonValue], timeout: float) -> bytes:
    if probe is None:
        raise HTTPException(
            status_code=503, detail=f"No media probe is set up; set {MEDIA_PROBE_URL_ENV} on the gateway"
        )
    try:
        response: Final = await probe.post(path, body, timeout)
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail=f"Could not reach the media probe: {error!r}") from error
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"The media probe answered {response.status_code}: {response.text[:300]}"
        )
    return response.content


def _probe_answer(answer: type[_Answer], content: bytes) -> _Answer:
    try:
        return answer.model_validate_json(content)
    except ValidationError as error:
        raise HTTPException(status_code=502, detail=f"The media probe's answer is not readable: {error}") from error


@router.get(
    "/qos/videos/evaluations/options",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosVideoEvaluationOptions,
)
async def get_qos_video_evaluation_options(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    probe: Annotated[MediaProbe | None, Depends(media_probe)],
) -> QosVideoEvaluationOptions:
    """What an evaluation run offers: the models the probe generates with, their latest price, and earlier prompts."""
    from litellm.proxy.proxy_server import llm_router, prisma_client

    require_video_reviewer(user_api_key_dict)
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    now: Final = utc_now()
    prompts: Final = USED_PROMPT_ROWS.validate_python(
        await query_rows(prisma_client, USED_PROMPTS_SQL, as_utc_naive(now - QOS_MAX_WINDOW))
    )
    prices: Final = LATEST_PRICE_ROWS.validate_python(
        await query_rows(prisma_client, LATEST_PRICES_SQL, as_utc_naive(now - PRICE_WINDOW))
    )
    deployments: Final = DEPLOYMENTS.validate_python((llm_router.get_model_list() if llm_router else None) or ())
    return QosVideoEvaluationOptions(
        available=probe is not None, models=probe_models(deployments, prices), prompts=prompts
    )


@router.post(
    "/qos/videos/evaluations/prompt",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosVideoEvaluationPrompt,
)
async def write_qos_video_evaluation_prompt(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    probe: Annotated[MediaProbe | None, Depends(media_probe)],
) -> QosVideoEvaluationPrompt:
    """A new test prompt that exercises every rating, unlike the recent ones, for the caller to read before a run."""
    from litellm.proxy.proxy_server import prisma_client

    require_admin(user_api_key_dict)
    recent: Final = (
        USED_PROMPT_ROWS.validate_python(
            await query_rows(prisma_client, USED_PROMPTS_SQL, as_utc_naive(utc_now() - QOS_MAX_WINDOW))
        )
        if prisma_client is not None
        else ()
    )
    content: Final = await _ask_probe(
        probe, "/prompts", {"avoid": [used.prompt for used in recent[:AVOIDED_PROMPTS]]}, PROMPT_TIMEOUT_SECONDS
    )
    return _probe_answer(QosVideoEvaluationPrompt, content)


@router.post(
    "/qos/videos/evaluations",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosVideoEvaluationStarted,
)
async def start_qos_video_evaluation(
    evaluation: QosVideoEvaluationRequest,
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    probe: Annotated[MediaProbe | None, Depends(media_probe)],
) -> QosVideoEvaluationStarted:
    """Have the probe generate the prompt's videos on every model it probes now, rating each as it finishes."""
    require_admin(user_api_key_dict)
    content: Final = await _ask_probe(probe, "/evaluations", {"prompt": evaluation.prompt}, START_TIMEOUT_SECONDS)
    return _probe_answer(QosVideoEvaluationStarted, content)


@router.put(
    "/qos/videos/evaluations/score",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosVideoAiReview,
)
async def put_qos_video_ai_review(
    video_id: Annotated[str, Query(min_length=1, description="The id the gateway returned for the video")],
    score: QosVideoAiScore,
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> QosVideoAiReview:
    """Keep the vision model's ratings of a video the probe made, replacing the ones it gave before."""
    from litellm.proxy.proxy_server import prisma_client

    require_admin(user_api_key_dict)
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    saved: Final = QosVideoAiReview.model_validate({**score.model_dump(), "reviewed_at": utc_now()})
    recorded: Final = RECORDED_REVIEW_ROWS.validate_python(
        await query_rows(prisma_client, RECORD_AI_REVIEW_SQL, video_id, saved.model_dump_json())
    )
    if not recorded:
        raise HTTPException(status_code=404, detail="No video with this id was made by the probe")
    return saved
