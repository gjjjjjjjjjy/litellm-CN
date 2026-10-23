"""
Per-account lockout for Admin UI password sign-in.

The failure count and lock time live in ``LiteLLM_UserTable.metadata`` and are changed by single
UPDATE statements, so concurrent failed sign-ins on several workers cannot lose an increment.
A locked account stays locked until a proxy admin unlocks it.
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from pydantic import ConfigDict, TypeAdapter

from litellm.types.llms.base import LiteLLMBaseModel

if TYPE_CHECKING:
    from litellm.proxy.utils import PrismaClient

LOGIN_LOCKOUT_THRESHOLD: Final = 3
FAILED_ATTEMPTS_KEY: Final = "login_failed_attempts"
LOCKED_AT_KEY: Final = "login_locked_at"
ACCOUNT_LOCKED_MESSAGE: Final = (
    f"This account is locked after {LOGIN_LOCKOUT_THRESHOLD} failed sign-in attempts. "
    "Ask an administrator to unlock it."
)

RECORD_FAILED_LOGIN_SQL: Final = f"""
UPDATE "LiteLLM_UserTable"
SET metadata = COALESCE(metadata, '{{}}'::jsonb)
    || jsonb_build_object('{FAILED_ATTEMPTS_KEY}', COALESCE((metadata->>'{FAILED_ATTEMPTS_KEY}')::int, 0) + 1)
    || CASE
        WHEN COALESCE((metadata->>'{FAILED_ATTEMPTS_KEY}')::int, 0) + 1 >= $2
        THEN jsonb_build_object('{LOCKED_AT_KEY}', to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
        ELSE '{{}}'::jsonb
    END
WHERE user_id = $1
RETURNING (metadata->>'{FAILED_ATTEMPTS_KEY}')::int AS failed_attempts
"""

CLEAR_LOGIN_FAILURES_SQL: Final = f"""
UPDATE "LiteLLM_UserTable"
SET metadata = metadata - '{FAILED_ATTEMPTS_KEY}' - '{LOCKED_AT_KEY}'
WHERE user_id = $1 AND (metadata ? '{FAILED_ATTEMPTS_KEY}' OR metadata ? '{LOCKED_AT_KEY}')
"""


class _FailedAttempts(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    failed_attempts: int


_FAILED_ATTEMPTS: Final = TypeAdapter(list[_FailedAttempts])


def is_account_locked(metadata: object) -> bool:
    return isinstance(metadata, Mapping) and metadata.get(LOCKED_AT_KEY) is not None


async def record_failed_login(prisma_client: "PrismaClient", user_id: str) -> bool:
    """Count one failed password sign-in and return whether the account is now locked."""
    (row,) = _FAILED_ATTEMPTS.validate_python(
        await prisma_client.db.query_raw(RECORD_FAILED_LOGIN_SQL, user_id, LOGIN_LOCKOUT_THRESHOLD)
    )
    return row.failed_attempts >= LOGIN_LOCKOUT_THRESHOLD


async def clear_login_failures(prisma_client: "PrismaClient", user_id: str) -> None:
    await prisma_client.db.execute_raw(CLEAR_LOGIN_FAILURES_SQL, user_id)
