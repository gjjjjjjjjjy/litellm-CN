"""Who may read service quality data and who may change it."""

from typing import Final

from fastapi import HTTPException

from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth

QOS_READ_ROLES: Final = (
    LitellmUserRoles.PROXY_ADMIN,
    LitellmUserRoles.PROXY_ADMIN_VIEW_ONLY,
    LitellmUserRoles.ORG_ADMIN,
    LitellmUserRoles.INTERNAL_USER,
    LitellmUserRoles.INTERNAL_USER_VIEW_ONLY,
)


def require_reader(user_api_key_dict: UserAPIKeyAuth) -> None:
    if user_api_key_dict.user_role not in QOS_READ_ROLES:
        raise HTTPException(status_code=403, detail="Only users of this gateway can view service quality metrics")


def require_admin(user_api_key_dict: UserAPIKeyAuth) -> None:
    if user_api_key_dict.user_role != LitellmUserRoles.PROXY_ADMIN:
        raise HTTPException(status_code=403, detail="Only proxy admins can change service quality data")
