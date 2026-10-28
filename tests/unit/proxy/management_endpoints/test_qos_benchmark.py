import asyncio
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Final, Literal

import httpx
import pytest
from pydantic import ValidationError

from litellm.proxy.management_endpoints.qos_benchmark import (
    concurrency_of,
    level_tag,
    new_run_id,
    run_and_record,
    run_benchmark,
)
from litellm.proxy.management_endpoints.qos_response_check import ResponseCheck, ResponseCheckRecorder
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
        self.checks: list[ResponseCheck] = []  # mutable-ok: test double records checks in hand-over order

    def record(self, check: ResponseCheck) -> None:
        self.checks.append(check)


def _plan(**overrides: object) -> QosBenchmarkRequest:
    return QosBenchmarkRequest.model_validate(
        {"model_group": "qwen3-max", "concurrency": (1, 3), "requests_per_worker": 2, "max_tokens": 64, **overrides}
    )


async def _run(
    upstream: _RecordingUpstream,
    plan: QosBenchmarkRequest,
    api_key: str | None,
    recorder: _CheckRecorder | None = None,
    handle: Callable[[httpx.Request], Awaitable[httpx.Response]] | None = None,
) -> _CheckRecorder:
    checks: Final = _CheckRecorder() if recorder is None else recorder
    transport: Final = httpx.MockTransport(upstream.handle if handle is None else handle)
    async with httpx.AsyncClient(transport=transport) as client:
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
    assert len(recorder.checks) == 3


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
    assert sorted(check.call_id for check in recorder.checks) == sorted(call_ids)
    assert {check.verdict for check in recorder.checks} == {"passed"}
    assert all(check.exchange is None for check in recorder.checks)


@pytest.mark.asyncio
async def test_saves_the_exact_question_and_keeps_reasoning_separate_from_the_answer() -> None:
    upstream: Final = _RecordingUpstream()

    async def handle(request: httpx.Request) -> httpx.Response:
        upstream.requests.append(request)
        marker: Final = _MARKER.findall(json.loads(request.content)["messages"][0]["content"])[0]
        chunks: Final = (
            {"choices": [{"delta": {"reasoning_content": "think first"}}]},
            {"choices": [{"delta": {"content": marker + "\n"}}]},
            {"choices": [{"delta": {"content": "<answer>\n第二行"}}]},
        )
        return httpx.Response(200, text="".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks))

    recorder: Final = await _run(
        upstream, _plan(concurrency=(1,), requests_per_worker=1, save_responses=True), None, handle=handle
    )
    (check,) = recorder.checks
    question: Final = json.loads(upstream.requests[0].content)["messages"][0]["content"]
    assert check.exchange is not None
    assert check.exchange.question == question
    assert check.exchange.answer == _MARKER.findall(question)[0] + "\n<answer>\n第二行"
    assert (check.exchange.reasoning, check.exchange.error, check.verdict) == ("think first", None, "passed")


class _FragmentedSSE(httpx.AsyncByteStream):
    def __init__(self, payload: str) -> None:
        self.payload: Final = payload.encode("utf-8")

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for offset in range(0, len(self.payload), 7):
            yield self.payload[offset : offset + 7]


@pytest.mark.parametrize("errors", ((), ("",), ("first\nline", "", "last")))
@pytest.mark.asyncio
async def test_fragmented_streams_keep_all_answer_reasoning_and_error_text(errors: tuple[str, ...]) -> None:
    upstream: Final = _RecordingUpstream()
    answer_parts: Final = tuple(f"第{index}段<answer>\n" for index in range(256))
    reasoning_parts: Final = tuple(f"Reasoning {index}\n" for index in range(256))

    async def handle(request: httpx.Request) -> httpx.Response:
        upstream.requests.append(request)
        marker: Final = _MARKER.findall(json.loads(request.content)["messages"][0]["content"])[0]
        chunks: Final = tuple(
            {"choices": [{"delta": {"content": answer, "reasoning_content": reasoning}}]}
            for answer, reasoning in zip(answer_parts, reasoning_parts, strict=True)
        )
        events: Final = "".join(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n" for chunk in chunks)
        error_events: Final = "".join(f"data: {json.dumps({'error': {'message': error}})}\n\n" for error in errors)
        return httpx.Response(
            200,
            stream=_FragmentedSSE(
                _sse(marker).removesuffix("data: [DONE]\n\n") + events + error_events + "data: [DONE]\n\n"
            ),
        )

    recorder: Final = await _run(
        upstream, _plan(concurrency=(1,), requests_per_worker=1, save_responses=True), None, handle=handle
    )
    (check,) = recorder.checks
    assert check.exchange is not None
    marker: Final = _MARKER.findall(check.exchange.question)[0]
    assert check.exchange.answer == marker + "".join(answer_parts)
    assert check.exchange.reasoning == "".join(reasoning_parts)
    assert check.exchange.error == ("\n".join(errors) if errors else None)
    assert check.verdict == (None if errors else "passed")


@pytest.mark.asyncio
async def test_saves_the_question_and_http_error_when_the_provider_rejects_a_request() -> None:
    upstream: Final = _RecordingUpstream()

    async def handle(request: httpx.Request) -> httpx.Response:
        upstream.requests.append(request)
        return httpx.Response(429, json={"error": {"message": "rate limit exceeded"}})

    recorder: Final = await _run(
        upstream, _plan(concurrency=(1,), requests_per_worker=1, save_responses=True), None, handle=handle
    )
    (check,) = recorder.checks
    assert check.verdict is None
    assert check.exchange is not None
    assert check.exchange.question == json.loads(upstream.requests[0].content)["messages"][0]["content"]
    assert (check.exchange.answer, check.exchange.reasoning) == (None, None)
    assert check.exchange.error is not None
    assert "HTTP 429" in check.exchange.error
    assert "rate limit exceeded" in check.exchange.error


@pytest.mark.asyncio
async def test_saves_a_transport_failure_only_when_response_saving_is_enabled() -> None:
    recorder: Final = await _run(
        _RecordingUpstream(fail_first=1),
        _plan(concurrency=(1,), requests_per_worker=1, save_responses=True),
        None,
    )
    (check,) = recorder.checks
    assert check.verdict is None
    assert check.exchange is not None
    assert check.exchange.error == "node unreachable"
    assert (check.exchange.answer, check.exchange.reasoning) == (None, None)


@pytest.mark.asyncio
async def test_a_stream_error_is_saved_instead_of_passing_a_partial_answer_with_the_right_code() -> None:
    upstream: Final = _RecordingUpstream()

    async def handle(request: httpx.Request) -> httpx.Response:
        upstream.requests.append(request)
        marker: Final = _MARKER.findall(json.loads(request.content)["messages"][0]["content"])[0]
        error: Final = {"error": {"message": "upstream stream interrupted"}}
        partial: Final = _sse(marker).removesuffix("data: [DONE]\n\n")
        return httpx.Response(200, text=partial + f"data: {json.dumps(error)}\n\ndata: [DONE]\n\n")

    recorder: Final = await _run(
        upstream, _plan(concurrency=(1,), requests_per_worker=1, save_responses=True), None, handle=handle
    )
    (check,) = recorder.checks
    assert check.verdict is None
    assert check.exchange is not None
    assert check.exchange.error == "upstream stream interrupted"
    assert check.exchange.answer == _MARKER.findall(check.exchange.question)[0]


@pytest.mark.parametrize(("answer", "expected"), [("previous", "crosstalk"), ("none", "marker_missing")])
@pytest.mark.asyncio
async def test_a_response_without_its_own_code_is_flagged(answer: Literal["previous", "none"], expected: str) -> None:
    recorder: Final = await _run(_RecordingUpstream(answer=answer), _plan(concurrency=(2,)), "sk-master")

    assert {check.verdict for check in recorder.checks} == {expected}


@pytest.mark.asyncio
async def test_each_check_is_handed_over_as_soon_as_its_request_finishes() -> None:
    upstream: Final = _RecordingUpstream()
    recorder: Final = _CheckRecorder()
    handed_over_before: Final[list[int]] = []  # mutable-ok: test double records progress at each arrival

    async def handle(request: httpx.Request) -> httpx.Response:
        handed_over_before.append(len(recorder.checks))
        return await upstream.handle(request)

    await _run(upstream, _plan(concurrency=(1,), requests_per_worker=3), "sk-master", recorder, handle)

    assert handed_over_before == [0, 1, 2]


@pytest.mark.asyncio
async def test_verdicts_of_finished_requests_are_written_when_the_run_fails_part_way() -> None:
    upstream: Final = _RecordingUpstream()
    written: Final[list[str]] = []  # mutable-ok: test double records the call ids written

    async def handle(request: httpx.Request) -> httpx.Response:
        if len(upstream.requests) == 2:
            raise RuntimeError("gateway restarted")
        return await upstream.handle(request)

    async def write(checks: tuple[ResponseCheck, ...]) -> frozenset[str]:
        written.extend(check.call_id for check in checks)
        return frozenset(check.call_id for check in checks)

    recorder: Final = ResponseCheckRecorder(write, attempts=1, retry_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(RuntimeError, match="gateway restarted"):
            await run_and_record(
                client,
                "http://127.0.0.1:4000/",
                "sk-master",
                "qos-run",
                _plan(concurrency=(1,), requests_per_worker=3),
                recorder,
            )

    assert written == [request.headers["x-litellm-call-id"] for request in upstream.requests]
    assert len(written) == 2


@pytest.mark.asyncio
async def test_a_failed_worker_cancels_and_awaits_its_siblings_before_the_recorder_closes() -> None:
    requests: Final[list[httpx.Request]] = []  # mutable-ok: test transport records request arrivals
    written: Final[list[str]] = []  # mutable-ok: test writer records persisted call ids
    pending_started: Final = asyncio.Event()
    pending_cancelled: Final = asyncio.Event()
    pending_finished: Final = asyncio.Event()
    release_pending: Final = asyncio.Event()
    first_written: Final = asyncio.Event()

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        arrival: Final = len(requests)
        marker: Final = _MARKER.findall(json.loads(request.content)["messages"][0]["content"])[0]
        if arrival == 1:
            await pending_started.wait()
            return httpx.Response(200, text=_sse(marker))
        if arrival == 2:
            await first_written.wait()
            raise RuntimeError("worker failed")
        pending_started.set()
        try:
            await release_pending.wait()
            return httpx.Response(200, text=_sse(marker))
        except asyncio.CancelledError:
            await asyncio.sleep(0)
            pending_cancelled.set()
            raise
        finally:
            pending_finished.set()

    async def write(checks: tuple[ResponseCheck, ...]) -> frozenset[str]:
        written.extend(check.call_id for check in checks)
        first_written.set()
        return frozenset(check.call_id for check in checks)

    recorder: Final = ResponseCheckRecorder(write, attempts=1, retry_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        try:
            with pytest.raises(RuntimeError, match="worker failed"):
                await run_and_record(
                    client,
                    "http://127.0.0.1:4000/",
                    "sk-master",
                    "qos-run",
                    _plan(concurrency=(3, 1), requests_per_worker=1),
                    recorder,
                )
            assert pending_cancelled.is_set()
            assert pending_finished.is_set()
            assert len(requests) == 3
            assert written == [requests[0].headers["x-litellm-call-id"]]
        finally:
            release_pending.set()
            await pending_finished.wait()


@pytest.mark.asyncio
async def test_the_recorder_persists_all_32_concurrent_responses() -> None:
    requests: Final[list[httpx.Request]] = []  # mutable-ok: test transport records request arrivals
    written: Final[list[str]] = []  # mutable-ok: test writer records persisted call ids
    all_started: Final = asyncio.Event()

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 32:
            all_started.set()
        await all_started.wait()
        marker: Final = _MARKER.findall(json.loads(request.content)["messages"][0]["content"])[0]
        return httpx.Response(200, text=_sse(marker))

    async def write(checks: tuple[ResponseCheck, ...]) -> frozenset[str]:
        written.extend(check.call_id for check in checks)
        return frozenset(check.call_id for check in checks)

    recorder: Final = ResponseCheckRecorder(write, attempts=1, retry_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await run_and_record(
            client,
            "http://127.0.0.1:4000/",
            "sk-master",
            "qos-run",
            _plan(concurrency=(32,), requests_per_worker=1),
            recorder,
        )

    assert len(requests) == len(written) == 32
    assert set(written) == {request.headers["x-litellm-call-id"] for request in requests}


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
