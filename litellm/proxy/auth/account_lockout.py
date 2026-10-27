"""
Per-account lockout for Admin UI password sign-in.

Every third consecutive failure locks the account for a short time; the tenth locks it until a proxy admin
unlocks it. The count, the temporary lock expiry and the permanent lock time live in
``LiteLLM_UserTable.metadata`` and are changed by single UPDATE statements, so concurrent failed sign-ins
on several workers cannot lose an increment, and failures that arrive while the account is locked are not
counted. A successful sign-in or an admin unlock clears all three.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final, TypeAlias

from pydantic import ConfigDict, TypeAdapter

from litellm.types.llms.base import LiteLLMBaseModel

if TYPE_CHECKING:
    from litellm.proxy.utils import PrismaClient

TEMPORARY_LOCK_EVERY: Final = 3
TEMPORARY_LOCK_MINUTES: Final = 15
PERMANENT_LOCK_AFTER: Final = 10
FAILED_ATTEMPTS_KEY: Final = "login_failed_attempts"
LOCKED_UNTIL_KEY: Final = "login_locked_until"
LOCKED_AT_KEY: Final = "login_locked_at"
ACCOUNT_LOCKED_MESSAGE: Final = (
    f"This account is locked after {PERMANENT_LOCK_AFTER} failed sign-in attempts. Ask an administrator to unlock it."
)

_UTC_TIMESTAMP: Final = """to_char({value}, 'YYYY-MM-DD"T"HH24:MI:SS"Z"')"""
_NEXT_COUNT: Final = f"COALESCE((metadata->>'{FAILED_ATTEMPTS_KEY}')::int, 0) + 1"

RECORD_FAILED_LOGIN_SQL: Final = f"""
UPDATE "LiteLLM_UserTable"
SET metadata = metadata
    || jsonb_build_object('{FAILED_ATTEMPTS_KEY}', {_NEXT_COUNT})
    || CASE
        WHEN {_NEXT_COUNT} >= $2
        THEN jsonb_build_object('{LOCKED_AT_KEY}', {_UTC_TIMESTAMP.format(value="now() AT TIME ZONE 'utc'")})
        WHEN ({_NEXT_COUNT}) % $3 = 0
        THEN jsonb_build_object(
            '{LOCKED_UNTIL_KEY}',
            {_UTC_TIMESTAMP.format(value="now() AT TIME ZONE 'utc' + make_interval(mins => $4::int)")}
        )
        ELSE '{{}}'::jsonb
    END
WHERE user_id = $1
    AND NOT COALESCE(metadata ? '{LOCKED_AT_KEY}', false)
    AND COALESCE((metadata->>'{LOCKED_UNTIL_KEY}')::timestamptz, '-infinity'::timestamptz) <= now()
RETURNING metadata
"""

CURRENT_LOGIN_LOCK_SQL: Final = """
SELECT metadata FROM "LiteLLM_UserTable" WHERE user_id = $1
"""

CLEAR_LOGIN_FAILURES_SQL: Final = f"""
UPDATE "LiteLLM_UserTable"
SET metadata = metadata - '{FAILED_ATTEMPTS_KEY}' - '{LOCKED_UNTIL_KEY}' - '{LOCKED_AT_KEY}'
WHERE user_id = $1 AND metadata ?| array['{FAILED_ATTEMPTS_KEY}', '{LOCKED_UNTIL_KEY}', '{LOCKED_AT_KEY}']
"""


@dataclass(frozen=True, slots=True)
class PermanentLock:
    pass


@dataclass(frozen=True, slots=True)
class TemporaryLock:
    until: datetime

    def message(self, now: datetime) -> str:
        minutes: Final = max(math.ceil((self.until - now).total_seconds() / 60), 1)
        return f"Too many failed sign-in attempts. Try again in {minutes} minutes."


AccountLock: TypeAlias = PermanentLock | TemporaryLock | None


class _LockFields(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    login_locked_at: str | None = None
    login_locked_until: datetime | None = None


class _UpdatedRow(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    metadata: Mapping[str, object]


_UPDATED_ROWS: Final = TypeAdapter(list[_UpdatedRow])


def account_lock(metadata: object, now: datetime) -> AccountLock:
    if not isinstance(metadata, Mapping):
        return None
    fields: Final = _LockFields.model_validate(metadata)
    if fields.login_locked_at is not None:
        return PermanentLock()
    if fields.login_locked_until is not None and fields.login_locked_until > now:
        return TemporaryLock(until=fields.login_locked_until)
    return None


async def record_failed_login(prisma_client: "PrismaClient", user_id: str, now: datetime) -> AccountLock:
    """
    Count one failed password sign-in and return the lock it leaves the account in.

    A failure is only counted while the account is unlocked. Sign-ins checked against the account before a
    concurrent one locked it are refused with that lock instead, so parallel guesses cannot run the count past
    a temporary lock up to a permanent one.
    """
    counted: Final = _UPDATED_ROWS.validate_python(
        await prisma_client.db.query_raw(
            RECORD_FAILED_LOGIN_SQL, user_id, PERMANENT_LOCK_AFTER, TEMPORARY_LOCK_EVERY, TEMPORARY_LOCK_MINUTES
        )
    )
    rows: Final = counted or _UPDATED_ROWS.validate_python(
        await prisma_client.db.query_raw(CURRENT_LOGIN_LOCK_SQL, user_id)
    )
    return account_lock(rows[0].metadata, now) if rows else None


async def clear_login_failures(prisma_client: "PrismaClient", user_id: str) -> None:
    await prisma_client.db.execute_raw(CLEAR_LOGIN_FAILURES_SQL, user_id)
