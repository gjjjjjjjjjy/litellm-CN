import asyncio
import json
import re
from datetime import datetime
from itertools import chain
from typing import Final, Literal

import httpx
import pytest
from pydantic import ValidationError

from litellm.proxy.management_endpoints.qos_benchmark import concurrency_of, level_tag, new_run_id, run_benchmark
from litellm.proxy.management_endpoints.qos_response_check import ResponseCheck
from litellm.types.qos import QOS_BENCHMARK_MAX_REQUESTS, QosBenchmarkRequest

_MARKER: Final = re.compile(r"QOS-[0-9A-F]{12}")


def _sse(text: str) -> str:
    return f"data: {json.dumps({'choices': [{'delta': {'content': text}}]})}\n\ndata: [DONE]\n\n"


class _RecordingUpstream:
    """Streams back the request's own code, the previous request's code, or no code at all."""

    def __init__(self, fail_first: int = 0, answer: Literal["own", "previous", "none"] = "own") -> None:
        self.requests: list[httpx.Request] = []  # mutable-ok: test double records calls in arrival order
        self.in_flight = 0
        self.peak_by_tag: dict[str, int] = {}  # mutable-ok: test double tracks peak concurrency per level
        self.fail_first = fail_first
        self.answer = answer
        self.previous_marker = "QOS-000000000000"

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if len(self.requests) <= self.fail_first:
            raise httpx.ConnectError("node unreachable", request=request)
        level = request.headers["x-litellm-tags"].split(",")[1]
        own = _MARKER.findall(json.loads(request.content)["messages"][0]["content"])[0]
        shown = {"own": own, "previous": self.previous_marker, "none": ""}[self.answer]
        self.previous_marker = own
        self.in_flight += 1
        self.peak_by_tag[level] = max(self.peak_by_tag.get(level, 0), self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        return httpx.Response(200, text=_sse(f"{shown}\nthe answer"))


class _CheckRecorder:
    def __init__(self) -> None:
        self.batches: list[tuple[ResponseCheck, ...]] = []  # mutable-ok: test double records each level's batch

    async def record(self, checks: tuple[ResponseCheck, ...]) -> None:
        self.batches.append(checks)


def _plan(**overrides: object) -> QosBenchmarkRequest:
    return QosBenchmarkRequest.model_validate(
        {"model_group": "qwen3-max", "concurrency": (1, 3), "requests_per_worker": 2, "max_tokens": 64, **overrides}
    )


async def _run(
    upstream: _RecordingUpstream, plan: QosBenchmarkRequest, api_key: str | None, recorder: _CheckRecorder | None = None
) -> _CheckRecorder:
    checks: Final = _CheckRecorder() if recorder is None else recorder
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream.handle)) as client:
        await run_benchmark(client, "http://127.0.0.1:4000/", api_key, "qos-run", plan, checks.record)
    return checks


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

    recorder: Final = await _run(upstream, _plan(concurrency=(2,)), None)

    assert len(upstream.requests) == 4
    assert all("authorization" not in request.headers for request in upstream.requests)
    assert [len(batch) for batch in recorder.batches] == [3]


@pytest.mark.asyncio
async def test_each_request_asks_for_its_own_code_and_is_checked_under_the_call_id_it_sent() -> None:
    upstream: Final = _RecordingUpstream()

    recorder: Final = await _run(upstream, _plan(), "sk-master")

    markers: Final = [
        _MARKER.findall(json.loads(request.content)["messages"][0]["content"]) for request in upstream.requests
    ]
    assert all(len(found) == 1 for found in markers)
    assert len({found[0] for found in markers}) == len(upstream.requests)
    call_ids: Final = [request.headers["x-litellm-call-id"] for request in upstream.requests]
    assert len(set(call_ids)) == len(call_ids)
    assert [len(batch) for batch in recorder.batches] == [1 * 2, 3 * 2]
    recorded: Final = list(chain.from_iterable(recorder.batches))
    assert sorted(check.call_id for check in recorded) == sorted(call_ids)
    assert {check.verdict for check in recorded} == {"passed"}


@pytest.mark.parametrize(("answer", "expected"), [("previous", "crosstalk"), ("none", "marker_missing")])
@pytest.mark.asyncio
async def test_a_response_without_its_own_code_is_flagged(answer: Literal["previous", "none"], expected: str) -> None:
    recorder: Final = await _run(_RecordingUpstream(answer=answer), _plan(concurrency=(2,)), "sk-master")

    assert {check.verdict for check in chain.from_iterable(recorder.batches)} == {expected}


@pytest.mark.asyncio
async def test_a_provider_comparison_runs_every_level_against_each_deployment_in_turn() -> None:
    upstream: Final = _RecordingUpstream()

    await _run(upstream, _plan(deployment_ids=("node-moark", "node-gitee")), "sk-master")

    sent: Final = [
        (json.loads(request.content)["model"], request.headers["x-litellm-tags"]) for request in upstream.requests
    ]
    assert sent == (
        [("node-moark", "qos-run,qos-run@c1")] * 2
        + [("node-moark", "qos-run,qos-run@c3")] * 6
        + [("node-gitee", "qos-run,qos-run@c1")] * 2
        + [("node-gitee", "qos-run,qos-run@c3")] * 6
    )


class TestBenchmarkPlan:
    def test_each_compared_deployment_gets_the_whole_plan(self) -> None:
        assert _plan().total_requests == (1 + 3) * 2
        assert _plan(deployment_ids=("a", "b", "c")).total_requests == (1 + 3) * 2 * 3

    def test_a_comparison_counts_toward_the_request_limit(self) -> None:
        per_deployment: Final = _plan(concurrency=(256,), requests_per_worker=QOS_BENCHMARK_MAX_REQUESTS // 256)
        assert per_deployment.total_requests <= QOS_BENCHMARK_MAX_REQUESTS
        with pytest.raises(ValidationError):
            _plan(concurrency=(256,), requests_per_worker=QOS_BENCHMARK_MAX_REQUESTS // 256, deployment_ids=("a", "b"))

    def test_a_deployment_is_compared_only_once(self) -> None:
        with pytest.raises(ValidationError):
            _plan(deployment_ids=("a", "a"))

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
