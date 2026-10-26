"""Endpoints behind the home dashboard: AI news, announcements and recent gateway activity."""

from datetime import timedelta
from typing import Annotated, Final

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from litellm.proxy._types import CommonProxyErrors, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.management_endpoints.qos_access import require_admin, require_reader
from litellm.proxy.management_endpoints.qos_activity import (
    MODEL_ADDED_ROWS,
    MODELS_ADDED_SQL,
    NODE_TRANSITION_ROWS,
    NODE_TRANSITIONS_SQL,
    benchmark_event,
    model_added_event,
    node_event,
    timeline,
)
from litellm.proxy.management_endpoints.qos_announcements import (
    read_board,
    save_board,
    with_announcement,
    without_announcement,
)
from litellm.proxy.management_endpoints.qos_deployments import deployment_model_groups, deployment_target_lookup
from litellm.proxy.management_endpoints.qos_news import FEED_TIMEOUT_SECONDS, NewsCache, configured_feeds
from litellm.proxy.management_endpoints.qos_summary import BENCHMARK_RUNS, BENCHMARK_RUNS_SQL, utc_now
from litellm.repositories.config_repository import ConfigRepository
from litellm.types.qos import QosActivityResponse, QosAnnouncementCreate, QosAnnouncementsResponse, QosNewsResponse

router: Final = APIRouter()

NEWS_CACHE: Final = NewsCache()
_NEWS_HEADERS: Final = {"User-Agent": "QosLLM news reader (+https://github.com/BerriAI/litellm)"}


@router.get("/qos/home/news", tags=["qos"], dependencies=[Depends(user_api_key_auth)], response_model=QosNewsResponse)
async def get_qos_news(user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)]) -> QosNewsResponse:
    """Latest items of the configured AI news feeds, with the outcome of fetching each feed."""
    from litellm.proxy.proxy_server import general_settings

    require_reader(user_api_key_dict)
    feeds: Final = configured_feeds(general_settings)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(FEED_TIMEOUT_SECONDS), follow_redirects=True, headers=_NEWS_HEADERS
    ) as client:
        return await NEWS_CACHE.get(feeds, client)


@router.get(
    "/qos/home/activity",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosActivityResponse,
)
async def get_qos_activity(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    days: Annotated[int, Query(ge=1, le=31, description="How far back to look")] = 7,
) -> QosActivityResponse:
    """Nodes that went down or recovered, benchmark runs and newly added models, newest first."""
    from litellm.proxy.proxy_server import llm_router, prisma_client

    require_reader(user_api_key_dict)
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    end: Final = utc_now()
    start: Final = end - timedelta(days=days)
    target_of: Final = deployment_target_lookup(llm_router)
    transitions: Final = NODE_TRANSITION_ROWS.validate_python(
        await prisma_client.db.query_raw(NODE_TRANSITIONS_SQL, start)
    )
    runs: Final = BENCHMARK_RUNS.validate_python(
        await prisma_client.db.query_raw(BENCHMARK_RUNS_SQL, start, end, deployment_model_groups(llm_router))
    )
    models: Final = MODEL_ADDED_ROWS.validate_python(await prisma_client.db.query_raw(MODELS_ADDED_SQL, start))
    return QosActivityResponse(
        events=timeline(
            nodes=[node_event(row, target_of) for row in transitions],
            runs=[benchmark_event(run) for run in runs],
            models=[model_added_event(row) for row in models],
        )
    )


def _repository() -> ConfigRepository:
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    return ConfigRepository(prisma_client, use_writer=True)


@router.get(
    "/qos/announcements",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosAnnouncementsResponse,
)
async def list_qos_announcements(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> QosAnnouncementsResponse:
    require_reader(user_api_key_dict)
    board: Final = await read_board(_repository())
    return QosAnnouncementsResponse(announcements=board.announcements)


@router.post(
    "/qos/announcements",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosAnnouncementsResponse,
)
async def post_qos_announcement(
    draft: QosAnnouncementCreate,
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> QosAnnouncementsResponse:
    """Publish an announcement on the home dashboard; proxy admins only."""
    require_admin(user_api_key_dict)
    repository: Final = _repository()
    board: Final = await read_board(repository)
    updated: Final = with_announcement(board, draft, _author(user_api_key_dict))
    if not await save_board(repository, board, updated):
        raise HTTPException(status_code=409, detail="Announcements changed meanwhile; reload and post again")
    return QosAnnouncementsResponse(announcements=updated.announcements)


@router.delete(
    "/qos/announcements/{announcement_id}",
    tags=["qos"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=QosAnnouncementsResponse,
)
async def delete_qos_announcement(
    announcement_id: str,
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> QosAnnouncementsResponse:
    require_admin(user_api_key_dict)
    repository: Final = _repository()
    board: Final = await read_board(repository)
    if all(item.id != announcement_id for item in board.announcements):
        raise HTTPException(status_code=404, detail="No such announcement")
    updated: Final = without_announcement(board, announcement_id)
    if not await save_board(repository, board, updated):
        raise HTTPException(status_code=409, detail="Announcements changed meanwhile; reload and try again")
    return QosAnnouncementsResponse(announcements=updated.announcements)


def _author(user_api_key_dict: UserAPIKeyAuth) -> str:
    if user_api_key_dict.user_email is not None:
        return user_api_key_dict.user_email
    return "" if user_api_key_dict.user_id is None else user_api_key_dict.user_id
