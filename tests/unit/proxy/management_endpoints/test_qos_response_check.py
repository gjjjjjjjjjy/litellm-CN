import asyncio
import json
from datetime import datetime
from typing import Final
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from litellm.proxy.management_endpoints.qos_response_check import (
    RECORD_RESPONSE_CHECKS_SQL,
    ResponseCheck,
    ResponseCheckRecorder,
    chunk_text,
    marked_prompt,
    new_marker,
    verdict,
    write_response_checks,
)
from litellm.types.qos import QosBenchmarkExchange

OWN: Final = "QOS-0123456789AB"
OTHER: Final = "QOS-BA9876543210"
SINCE: Final = datetime(2026, 10, 23, 12, 0)


class TestVerdict:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            (f"{OWN}\nA large language model is", "passed"),
            (f"thinking about {OWN} first\n{OWN}\nanswer", "passed"),
            (f"{OTHER}\nanswer", "crosstalk"),
            (f"{OWN}\nanswer that drifted into {OTHER}", "crosstalk"),
            ("answer without any code", "marker_missing"),
            (f"{OWN.lower()}\nanswer", "marker_missing"),
        ],
    )
    def test_only_codes_of_other_requests_count_as_crosstalk(self, text: str, expected: str) -> None:
        assert verdict(OWN, text) == expected

    def test_every_request_gets_a_code_the_check_recognises(self) -> None:
        marker: Final = new_marker()
        assert marker != new_marker()
        assert verdict(marker, marked_prompt(marker, "prompt")) == "passed"


class TestChunkText:
    def test_reads_reasoning_and_answer_text_from_a_stream_chunk(self) -> None:
        line: Final = "data: " + json.dumps(
            {"id": "c", "choices": [{"delta": {"reasoning_content": "think ", "content": "answer"}}]}
        )
        assert chunk_text(line) == "think answer"

    @pytest.mark.parametrize("line", ["", ": keep-alive", "data: [DONE]", 'data: {"choices": []}'])
    def test_lines_without_generated_text_contribute_nothing(self, line: str) -> None:
        assert chunk_text(line) == ""

    def test_a_malformed_chunk_is_an_error_not_silence(self) -> None:
        with pytest.raises(ValidationError):
            chunk_text("data: {not json")


A: Final = ResponseCheck("a", "passed", None)
B: Final = ResponseCheck("b", "crosstalk", None)
C: Final = ResponseCheck("c", "passed", None)


class TestWriteResponseChecks:
    @pytest.mark.asyncio
    async def test_writes_every_verdict_in_one_query_and_reports_which_rows_existed(self) -> None:
        prisma: Final = MagicMock()
        prisma.db.query_raw = AsyncMock(return_value=[{"call_id": "a"}])

        written: Final = await write_response_checks(prisma, SINCE, (A, B))

        assert written == frozenset({"a"})
        sql, payload, since = prisma.db.query_raw.await_args.args
        assert (sql, since) == (RECORD_RESPONSE_CHECKS_SQL, SINCE)
        assert json.loads(payload) == [
            {"call_id": "a", "verdict": "passed", "exchange": None},
            {"call_id": "b", "verdict": "crosstalk", "exchange": None},
        ]

    @pytest.mark.asyncio
    async def test_the_same_batched_write_keeps_question_answer_and_reasoning(self) -> None:
        prisma: Final = MagicMock()
        prisma.db.query_raw = AsyncMock(return_value=[{"call_id": "a"}])
        exchange: Final = QosBenchmarkExchange(
            question="question\ncode", answer="answer", reasoning="think", error=None
        )

        await write_response_checks(prisma, SINCE, (ResponseCheck("a", "passed", exchange),))

        assert prisma.db.query_raw.await_count == 1
        assert json.loads(prisma.db.query_raw.await_args.args[1]) == [
            {"call_id": "a", "verdict": "passed", "exchange": exchange.model_dump()}
        ]


class _SpendLogs:
    """Accepts the verdicts whose rows exist, one list of call ids per round."""

    def __init__(self, *existing_per_round: frozenset[str]) -> None:
        self.rounds: list[tuple[str, ...]] = []  # mutable-ok: test double records each round's write
        self.existing = existing_per_round
        self.wrote = asyncio.Event()

    async def write(self, checks: tuple[ResponseCheck, ...]) -> frozenset[str]:
        self.rounds.append(tuple(check.call_id for check in checks))
        self.wrote.set()
        existing: Final = self.existing[len(self.rounds) - 1]
        return frozenset(check.call_id for check in checks if check.call_id in existing)


class TestResponseCheckRecorder:
    @pytest.mark.asyncio
    async def test_writes_verdicts_as_they_arrive_without_waiting_for_the_run_to_end(self) -> None:
        spend_logs: Final = _SpendLogs(frozenset({"a", "b"}), frozenset({"c"}))
        recorder: Final = ResponseCheckRecorder(spend_logs.write, attempts=3, retry_seconds=0)
        recorder.add(A)
        recorder.add(B)
        running: Final = asyncio.create_task(recorder.run())

        await asyncio.wait_for(spend_logs.wrote.wait(), timeout=1)

        assert spend_logs.rounds == [("a", "b")]
        assert not running.done()
        recorder.add(C)
        recorder.close()
        await asyncio.wait_for(running, timeout=1)
        assert spend_logs.rounds == [("a", "b"), ("c",)]

    @pytest.mark.asyncio
    async def test_retries_a_verdict_until_its_spend_log_appears(self) -> None:
        spend_logs: Final = _SpendLogs(frozenset({"a"}), frozenset(), frozenset({"b"}))
        recorder: Final = ResponseCheckRecorder(spend_logs.write, attempts=3, retry_seconds=0)
        recorder.add(A)
        recorder.add(B)
        recorder.close()

        await asyncio.wait_for(recorder.run(), timeout=1)

        assert spend_logs.rounds == [("a", "b"), ("b",), ("b",)]

    @pytest.mark.asyncio
    async def test_gives_up_on_a_verdict_after_its_last_attempt(self) -> None:
        spend_logs: Final = _SpendLogs(frozenset(), frozenset(), frozenset())
        recorder: Final = ResponseCheckRecorder(spend_logs.write, attempts=2, retry_seconds=0)
        recorder.add(A)
        recorder.close()

        await asyncio.wait_for(recorder.run(), timeout=1)

        assert spend_logs.rounds == [("a",), ("a",)]

    @pytest.mark.asyncio
    async def test_a_run_without_verdicts_writes_nothing(self) -> None:
        spend_logs: Final = _SpendLogs()
        recorder: Final = ResponseCheckRecorder(spend_logs.write, attempts=3, retry_seconds=0)
        recorder.close()

        await asyncio.wait_for(recorder.run(), timeout=1)

        assert spend_logs.rounds == []
