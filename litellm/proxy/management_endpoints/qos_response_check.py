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
from collections.abc import Awaitable, Callable
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


WriteChecks: TypeAlias = Callable[[tuple[ResponseCheck, ...]], Awaitable[frozenset[str]]]


@dataclass(frozen=True, slots=True)
class _Pending:
    check: ResponseCheck
    attempts_left: int


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


async def write_response_checks(
    prisma_client: "PrismaClient", since: datetime, checks: tuple[ResponseCheck, ...]
) -> frozenset[str]:
    """Write each verdict whose spend log row exists, returning the call ids written."""
    payload: Final = json.dumps([{"call_id": check.call_id, "verdict": check.verdict} for check in checks])
    return frozenset(
        row.call_id
        for row in _RECORDED.validate_python(
            await prisma_client.db.query_raw(RECORD_RESPONSE_CHECKS_SQL, payload, since)
        )
    )


class ResponseCheckRecorder:
    """
    Writes verdicts while the benchmark runs, so a request keeps its verdict even if the run stops part way.

    One query per round writes every verdict handed over since the last round, keeping the load on the gateway
    under test flat at any concurrency. A verdict whose spend log row the batched writer has not flushed yet is
    retried in later rounds until its attempts run out.
    """

    def __init__(self, write: WriteChecks, attempts: int, retry_seconds: float) -> None:
        self._write = write
        self._attempts = attempts
        self._retry_seconds = retry_seconds
        self._queue: Final[asyncio.Queue[_Pending]] = asyncio.Queue()
        self._closed: Final = asyncio.Event()

    def add(self, check: ResponseCheck) -> None:
        self._queue.put_nowait(_Pending(check=check, attempts_left=self._attempts))

    def close(self) -> None:
        """No more verdicts will arrive; run() returns once the ones handed over are written or given up."""
        self._closed.set()

    async def run(self) -> None:
        while await self._round():
            pass

    async def _round(self) -> bool:
        await asyncio.sleep(self._retry_seconds)
        closed: Final = self._closed.is_set()
        batch: Final = tuple(self._queue.get_nowait() for _ in range(self._queue.qsize()))
        written: Final = await self._write(tuple(item.check for item in batch)) if batch else frozenset[str]()
        unwritten: Final = tuple(item for item in batch if item.check.call_id not in written)
        retry: Final = tuple(
            _Pending(check=item.check, attempts_left=item.attempts_left - 1)
            for item in unwritten
            if item.attempts_left > 1
        )
        if len(retry) < len(unwritten):
            verbose_proxy_logger.warning(
                "QoS response checks for %s requests could not be recorded: their spend logs never appeared",
                len(unwritten) - len(retry),
            )
        for item in retry:
            self._queue.put_nowait(item)
        return not closed or bool(retry)
