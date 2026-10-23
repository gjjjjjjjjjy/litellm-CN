from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ConfigDict, Field

from litellm.proxy._types import CommonProxyErrors, LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.account_lockout import CLEAR_LOGIN_FAILURES_SQL
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.types.llms.base import LiteLLMBaseModel

router: Final = APIRouter()


class UnlockAccountRequest(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1)


class UnlockAccountResponse(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    unlocked: bool


@router.post(
    "/account_lockout/unlock",
    tags=["Internal User management"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=UnlockAccountResponse,
)
async def unlock_account(
    request: UnlockAccountRequest,
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> UnlockAccountResponse:
    """Clear a user's failed sign-in count and lock so they can sign in with their password again."""
    from litellm.proxy.proxy_server import prisma_client

    if user_api_key_dict.user_role != LitellmUserRoles.PROXY_ADMIN:
        raise HTTPException(status_code=403, detail="Only proxy admins can unlock accounts")
    if prisma_client is None:
        raise HTTPException(status_code=500, detail=CommonProxyErrors.db_not_connected_error.value)
    changed: Final = await prisma_client.db.execute_raw(CLEAR_LOGIN_FAILURES_SQL, request.user_id)
    return UnlockAccountResponse(user_id=request.user_id, unlocked=changed > 0)
