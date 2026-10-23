from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.account_lockout import CLEAR_LOGIN_FAILURES_SQL
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.management_endpoints.account_lockout_endpoints import router


def _client(role: LitellmUserRoles) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[user_api_key_auth] = lambda: UserAPIKeyAuth(api_key="sk-test", user_role=role)
    return TestClient(app)


@pytest.mark.parametrize(
    "role",
    [LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY, LitellmUserRoles.INTERNAL_USER, LitellmUserRoles.ORG_ADMIN],
)
def test_only_proxy_admins_can_unlock_accounts(role: LitellmUserRoles) -> None:
    prisma = MagicMock()
    prisma.db.execute_raw = AsyncMock()
    with patch("litellm.proxy.proxy_server.prisma_client", prisma):
        response = _client(role).post("/account_lockout/unlock", json={"user_id": "locked-user"})
    assert response.status_code == 403
    prisma.db.execute_raw.assert_not_awaited()


@pytest.mark.parametrize(("rows_changed", "unlocked"), [(1, True), (0, False)])
def test_unlocking_clears_the_users_failed_sign_ins(rows_changed: int, unlocked: bool) -> None:
    prisma = MagicMock()
    prisma.db.execute_raw = AsyncMock(return_value=rows_changed)
    with patch("litellm.proxy.proxy_server.prisma_client", prisma):
        response = _client(LitellmUserRoles.PROXY_ADMIN).post(
            "/account_lockout/unlock", json={"user_id": "locked-user"}
        )

    assert response.status_code == 200
    assert response.json() == {"user_id": "locked-user", "unlocked": unlocked}
    prisma.db.execute_raw.assert_awaited_once_with(CLEAR_LOGIN_FAILURES_SQL, "locked-user")
