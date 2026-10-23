import asyncio
import json
from datetime import datetime
from typing import Final

import httpx
import pytest
from pydantic import ValidationError

from litellm.proxy.management_endpoints.qos_benchmark import concurrency_of, level_tag, new_run_id, run_benchmark
from litellm.types.qos import QOS_BENCHMARK_MAX_REQUESTS, QosBenchmarkRequest


class _RecordingUpstream:
    def __init__(self, fail_first: int = 0) -> None:
        self.requests: list[httpx.Request] = []  # mutable-ok: test double records calls in arrival order
        self.in_flight = 0
        self.peak_by_tag: dict[str, int] = {}  # mutable-ok: test double tracks peak concurrency per level
        self.fail_first = fail_first

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if len(self.requests) <= self.fail_first:
            raise httpx.ConnectError("node unreachable", request=request)
        level = request.headers["x-litellm-tags"].split(",")[1]
        self.in_flight += 1
        self.peak_by_tag[level] = max(self.peak_by_tag.get(level, 0), self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        return httpx.Response(200, text='data: {"choices": []}\n\ndata: [DONE]\n\n')


def _plan(**overrides: object) -> QosBenchmarkRequest:
    return QosBenchmarkRequest.model_validate(
        {"model_group": "qwen3-max", "concurrency": (1, 3), "requests_per_worker": 2, "max_tokens": 64, **overrides}
    )


async def _run(upstream: _RecordingUpstream, plan: QosBenchmarkRequest, api_key: str | None) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream.handle)) as client:
        await run_benchmark(client, "http://127.0.0.1:4000/", api_key, "qos-run", plan)


@pytest.mark.asyncio
async def test_each_level_runs_at_its_concurrency_in_order_with_run_and_level_tags() -> None:
    upstream: Final = _RecordingUpstream()

    await _run(upstream, _plan(), "sk-master")

    assert len(upstream.requests) == (1 + 3) * 2
    levels: Final = [request.headers["x-litellm-tags"] for request in upstream.requests]
    assert levels == ["qos-run,qos-run@c1"] * 2 + ["qos-run,qos-run@c3"] * 6
    assert upstream.peak_by_tag == {"qos-run@c1": 1, "qos-run@c3": 3}
    first: Final = upstream.requests[0]
    assert str(first.url) == "http://127.0.0.1:4000/v1/chat/completions"
    assert first.headers["authorization"] == "Bearer sk-master"
    body: Final = json.loads(first.content)
    assert (body["model"], body["stream"], body["max_tokens"]) == ("qwen3-max", True, 64)
    assert body["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_a_failed_request_does_not_stop_the_run_and_no_key_sends_no_auth_header() -> None:
    upstream: Final = _RecordingUpstream(fail_first=1)

    await _run(upstream, _plan(concurrency=(2,)), None)

    assert len(upstream.requests) == 4
    assert all("authorization" not in request.headers for request in upstream.requests)


class TestBenchmarkPlan:
    def test_total_requests_is_bounded(self) -> None:
        limit_per_worker: Final = QOS_BENCHMARK_MAX_REQUESTS // 256
        assert (
            _plan(concurrency=(256,), requests_per_worker=limit_per_worker).total_requests <= QOS_BENCHMARK_MAX_REQUESTS
        )
        with pytest.raises(ValidationError):
            _plan(concurrency=(256, 256), requests_per_worker=limit_per_worker)

    def test_concurrency_levels_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            _plan(concurrency=(0,))
        with pytest.raises(ValidationError):
            _plan(concurrency=())


class TestRunIds:
    def test_run_id_is_tag_safe_and_unique_per_start(self) -> None:
        now: Final = datetime(2026, 10, 23, 9, 30, 5)
        first: Final = new_run_id("moark/Qwen3 Max_v2", now)
        assert first.startswith("qos-20261023-093005-moark-Qwen3-Max-v2-")
        assert all(character.isalnum() or character in ".-" for character in first)
        assert first != new_run_id("moark/Qwen3 Max_v2", now)

    def test_level_tag_round_trips_to_its_concurrency(self) -> None:
        assert concurrency_of(level_tag("qos-run", 16), "qos-run") == 16
