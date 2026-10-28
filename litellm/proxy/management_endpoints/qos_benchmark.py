import asyncio
import re
import secrets
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from io import StringIO
from itertools import product
from typing import Final, TypeAlias

import httpx
from pydantic import ValidationError

from litellm._logging import verbose_proxy_logger
from litellm.proxy.management_endpoints.qos_response_check import (
    ResponseCheck,
    ResponseCheckRecorder,
    ResponseText,
    chunk_parts,
    marked_prompt,
    new_marker,
    saved_exchange,
    verdict,
)
from litellm.types.qos import QosBenchmarkRequest

QOS_RUN_PREFIX: Final = "qos-"
_LEVEL_SEPARATOR: Final = "@c"
_RUN_ID_UNSAFE: Final = re.compile(r"[^A-Za-z0-9.-]+")
BENCHMARK_PROMPTS: Final = (
    "用三句话解释什么是大语言模型。",
    "写一个 Python 函数，判断一个字符串是否是回文，并给出两个测试用例。",
    "列出提升网站加载速度的五种方法，每条一句话说明原因。",
    "简要比较 TCP 和 UDP 的区别，并各举一个适用场景。",
    "一个水池单开甲管 6 小时注满，单开乙管 4 小时注满，两管同时开需要几小时？请给出推理过程。",
    "解释数据库索引的工作原理，以及为什么索引过多会影响写入性能。",
    "用通俗的语言解释什么是 Transformer 中的注意力机制。",
    "如果一个 API 的 P95 延迟突然升高，你会按什么步骤排查？",
    "Explain the CAP theorem in distributed systems in simple terms.",
    "Write a SQL query that returns the top 3 customers by total order amount.",
    "Summarize the benefits and risks of remote work in five bullet points.",
    "Write a short email to a colleague asking to reschedule a meeting from Monday to Wednesday.",
)

_running: Final[set[asyncio.Task[None]]] = set()  # mutable-ok: keeps background runs referenced until they finish


def new_run_id(model_group: str, now: datetime) -> str:
    model_slug: Final = _RUN_ID_UNSAFE.sub("-", model_group).strip("-")
    return f"{QOS_RUN_PREFIX}{now:%Y%m%d-%H%M%S}-{model_slug}-{secrets.token_hex(2)}"


def level_tag(run_id: str, concurrency: int) -> str:
    return f"{run_id}{_LEVEL_SEPARATOR}{concurrency}"


def concurrency_of(tag: str, run_id: str) -> int:
    return int(tag.removeprefix(f"{run_id}{_LEVEL_SEPARATOR}"))


RecordCheck: TypeAlias = Callable[[ResponseCheck], None]


async def _send(
    client: httpx.AsyncClient,
    url: str,
    headers: Mapping[str, str],
    body: Mapping[str, object],
    marker: str,
    call_id: str,
    question: str | None,
) -> ResponseCheck:
    async with client.stream("POST", url, json=body, headers={**headers, "x-litellm-call-id": call_id}) as response:
        if response.status_code >= 400:
            await response.aread()
            error: Final = f"HTTP {response.status_code}: {response.text}"
            verbose_proxy_logger.warning("QoS benchmark request failed with HTTP %s", response.status_code)
            return ResponseCheck(call_id=call_id, verdict=None, exchange=saved_exchange(question, None, None, error))
        with StringIO() as answer, StringIO() as reasoning, StringIO() as errors:
            async for part in (chunk_parts(line) async for line in response.aiter_lines()):
                answer.write(part.answer)
                reasoning.write(part.reasoning)
                if part.error is not None:
                    errors.write(part.error + "\n")
            text: Final = ResponseText(
                answer=answer.getvalue(),
                reasoning=reasoning.getvalue(),
                error=errors.getvalue()[:-1] if errors.tell() > 0 else None,
            )
        return ResponseCheck(
            call_id=call_id,
            verdict=verdict(marker, text.reasoning + text.answer) if text.error is None else None,
            exchange=saved_exchange(question, text.answer, text.reasoning, text.error),
        )


def _request_body(plan: QosBenchmarkRequest, target: str, prompt: str) -> Mapping[str, object]:
    return {
        "model": target,
        "stream": True,
        "max_tokens": plan.max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }


async def _attempt(
    client: httpx.AsyncClient,
    url: str,
    headers: Mapping[str, str],
    plan: QosBenchmarkRequest,
    target: str,
    sequence: int,
) -> ResponseCheck:
    marker: Final = new_marker()
    call_id: Final = uuid.uuid4().hex
    prompt: Final = marked_prompt(marker, BENCHMARK_PROMPTS[sequence % len(BENCHMARK_PROMPTS)])
    question: Final = prompt if plan.save_responses else None
    try:
        return await _send(client, url, headers, _request_body(plan, target, prompt), marker, call_id, question)
    except (httpx.HTTPError, ValidationError) as error:
        verbose_proxy_logger.warning("QoS benchmark request did not complete: %s", error)
        return ResponseCheck(call_id=call_id, verdict=None, exchange=saved_exchange(question, None, None, str(error)))


async def _worker(
    client: httpx.AsyncClient,
    url: str,
    headers: Mapping[str, str],
    plan: QosBenchmarkRequest,
    target: str,
    worker_index: int,
    record: RecordCheck,
) -> None:
    first: Final = worker_index * plan.requests_per_worker
    for sequence in range(first, first + plan.requests_per_worker):
        if (
            check := await _attempt(client, url, headers, plan, target, sequence)
        ).verdict is None and check.exchange is None:
            continue
        record(check)


def _level_headers(auth: Mapping[str, str], run_id: str, concurrency: int) -> Mapping[str, str]:
    return {**auth, "x-litellm-tags": f"{run_id},{level_tag(run_id, concurrency)}"}


async def _run_level(
    client: httpx.AsyncClient,
    url: str,
    headers: Mapping[str, str],
    plan: QosBenchmarkRequest,
    target: str,
    concurrency: int,
    record: RecordCheck,
) -> None:
    workers: Final = tuple(
        asyncio.create_task(_worker(client, url, headers, plan, target, index, record)) for index in range(concurrency)
    )
    try:
        await asyncio.gather(*workers)
    finally:
        for worker in workers:
            if not worker.done():
                worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


async def run_benchmark(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str | None,
    run_id: str,
    plan: QosBenchmarkRequest,
    record: RecordCheck,
) -> None:
    """Run every level against each target in turn, handing over each response check as its request finishes."""
    url: Final = f"{base_url.rstrip('/')}/v1/chat/completions"
    auth: Final = {} if api_key is None else {"Authorization": f"Bearer {api_key}"}
    for target, concurrency in product(plan.targets, plan.concurrency):
        await _run_level(client, url, _level_headers(auth, run_id, concurrency), plan, target, concurrency, record)


async def run_and_record(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str | None,
    run_id: str,
    plan: QosBenchmarkRequest,
    recorder: ResponseCheckRecorder,
) -> None:
    """Run the benchmark while the recorder writes verdicts; verdicts of finished requests are written even if it fails."""
    recording: Final = asyncio.create_task(recorder.run())
    try:
        await run_benchmark(client, base_url, api_key, run_id, plan, recorder.add)
    finally:
        recorder.close()
        await recording


async def _run_in_background(
    base_url: str, api_key: str | None, run_id: str, plan: QosBenchmarkRequest, recorder: ResponseCheckRecorder
) -> None:
    limits: Final = httpx.Limits(max_connections=max(plan.concurrency), max_keepalive_connections=max(plan.concurrency))
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0), limits=limits) as client:
        await run_and_record(client, base_url, api_key, run_id, plan, recorder)
    verbose_proxy_logger.info("QoS benchmark %s finished", run_id)


def start_benchmark(
    base_url: str, api_key: str | None, run_id: str, plan: QosBenchmarkRequest, recorder: ResponseCheckRecorder
) -> None:
    task: Final = asyncio.create_task(_run_in_background(base_url, api_key, run_id, plan, recorder))
    _running.add(task)
    task.add_done_callback(_running.discard)
