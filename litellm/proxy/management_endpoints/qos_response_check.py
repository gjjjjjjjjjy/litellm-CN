"""
Cross-talk check for QoS benchmark responses.

Every benchmark request asks the model to repeat a code unique to that request. A response carrying another
request's code was mixed up with a concurrent request somewhere between the gateway and the model. The verdict
is written onto the request's own spend log row, so it is kept and deleted together with the run's metrics.
"""

import asyncio
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final, Literal, TypeAlias

from pydantic import ConfigDict, TypeAdapter

from litellm._logging import verbose_proxy_logger
from litellm.types.llms.base import LiteLLMBaseModel

if TYPE_CHECKING:
    from litellm.proxy.utils import PrismaClient

RESPONSE_CHECK_KEY: Final = "qos_response_check"
_MARKER: Final = re.compile(r"QOS-[0-9A-F]{12}")
_SSE_DATA_PREFIX: Final = "data:"

ResponseVerdict: TypeAlias = Literal["passed", "crosstalk", "marker_missing"]

RECORD_RESPONSE_CHECKS_SQL: Final = f"""
UPDATE "LiteLLM_SpendLogs" AS logs
SET metadata = COALESCE(logs.metadata, '{{}}'::jsonb) || jsonb_build_object('{RESPONSE_CHECK_KEY}', checks.verdict)
FROM jsonb_to_recordset($1::jsonb) AS checks(call_id text, verdict text)
WHERE logs.litellm_call_id = checks.call_id AND logs."startTime" >= $2::timestamp
RETURNING logs.litellm_call_id AS call_id
"""


@dataclass(frozen=True, slots=True)
class ResponseCheck:
    call_id: str
    verdict: ResponseVerdict


class _Delta(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    content: str | None = None
    reasoning_content: str | None = None


class _Choice(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    delta: _Delta


class _Chunk(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    choices: tuple[_Choice, ...] = ()


class _Recorded(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str


_RECORDED: Final = TypeAdapter(list[_Recorded])


def new_marker() -> str:
    return f"QOS-{secrets.token_hex(6).upper()}"


def marked_prompt(marker: str, prompt: str) -> str:
    return f"Write the code {marker} alone on the first line of your reply, then answer:\n\n{prompt}"


def chunk_text(line: str) -> str:
    """The generated text in one server-sent event line of a streamed chat completion, reasoning included."""
    if not line.startswith(_SSE_DATA_PREFIX):
        return ""
    data: Final = line.removeprefix(_SSE_DATA_PREFIX).strip()
    if data == "[DONE]":
        return ""
    return "".join(_delta_text(choice.delta) for choice in _Chunk.model_validate_json(data).choices)


def _delta_text(delta: _Delta) -> str:
    return "".join(part for part in (delta.reasoning_content, delta.content) if part is not None)


def verdict(marker: str, text: str) -> ResponseVerdict:
    markers: Final = frozenset(_MARKER.findall(text))
    if markers - {marker}:
        return "crosstalk"
    if marker in markers:
        return "passed"
    return "marker_missing"


async def record_response_checks(
    prisma_client: "PrismaClient",
    checks: tuple[ResponseCheck, ...],
    since: datetime,
    attempts: int,
    retry_seconds: float,
) -> None:
    """Write each verdict onto its spend log row, retrying while the batched spend log writer catches up."""
    if not checks:
        return
    payload: Final = json.dumps([{"call_id": check.call_id, "verdict": check.verdict} for check in checks])
    recorded: Final = frozenset(
        row.call_id
        for row in _RECORDED.validate_python(
            await prisma_client.db.query_raw(RECORD_RESPONSE_CHECKS_SQL, payload, since)
        )
    )
    remaining: Final = tuple(check for check in checks if check.call_id not in recorded)
    if not remaining:
        return
    if attempts == 1:
        verbose_proxy_logger.warning(
            "QoS response checks for %s requests could not be recorded: their spend logs never appeared", len(remaining)
        )
        return
    await asyncio.sleep(retry_seconds)
    await record_response_checks(prisma_client, remaining, since, attempts - 1, retry_seconds)
