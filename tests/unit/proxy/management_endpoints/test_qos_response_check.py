import json
from datetime import datetime
from typing import Final
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from litellm.proxy.management_endpoints.qos_response_check import (
    RECORD_RESPONSE_CHECKS_SQL,
    ResponseCheck,
    chunk_text,
    marked_prompt,
    new_marker,
    record_response_checks,
    verdict,
)

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


def _prisma(*recorded_batches: list[str]) -> MagicMock:
    prisma = MagicMock()
    prisma.db.query_raw = AsyncMock(
        side_effect=[[{"call_id": call_id} for call_id in batch] for batch in recorded_batches]
    )
    return prisma


def _sent_call_ids(prisma: MagicMock) -> list[list[str]]:
    return [[check["call_id"] for check in json.loads(call.args[1])] for call in prisma.db.query_raw.await_args_list]


class TestRecordResponseChecks:
    CHECKS: Final = (ResponseCheck("a", "passed"), ResponseCheck("b", "crosstalk"), ResponseCheck("c", "passed"))

    @pytest.mark.asyncio
    async def test_retries_only_the_checks_whose_spend_logs_were_not_written_yet(self) -> None:
        prisma: Final = _prisma(["a"], ["b", "c"])

        await record_response_checks(prisma, self.CHECKS, SINCE, attempts=3, retry_seconds=0)

        assert _sent_call_ids(prisma) == [["a", "b", "c"], ["b", "c"]]
        first: Final = prisma.db.query_raw.await_args_list[0].args
        assert (first[0], first[2]) == (RECORD_RESPONSE_CHECKS_SQL, SINCE)
        assert json.loads(first[1])[1] == {"call_id": "b", "verdict": "crosstalk"}

    @pytest.mark.asyncio
    async def test_stops_after_the_last_attempt(self) -> None:
        prisma: Final = _prisma([], [], [])

        await record_response_checks(prisma, self.CHECKS, SINCE, attempts=2, retry_seconds=0)

        assert prisma.db.query_raw.await_count == 2

    @pytest.mark.asyncio
    async def test_a_level_without_checks_touches_nothing(self) -> None:
        prisma: Final = _prisma()

        await record_response_checks(prisma, (), SINCE, attempts=3, retry_seconds=0)

        prisma.db.query_raw.assert_not_awaited()
