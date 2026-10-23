import asyncio
import re
import secrets
from collections.abc import Mapping
from datetime import datetime
from typing import Final

import httpx

from litellm._logging import verbose_proxy_logger
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


async def _send(client: httpx.AsyncClient, url: str, headers: Mapping[str, str], body: Mapping[str, object]) -> None:
    async with client.stream("POST", url, json=body, headers=headers) as response:
        async for _ in response.aiter_bytes():
            pass
        if response.status_code >= 400:
            verbose_proxy_logger.warning("QoS benchmark request failed with HTTP %s", response.status_code)


def _request_body(plan: QosBenchmarkRequest, sequence: int) -> Mapping[str, object]:
    return {
        "model": plan.model_group,
        "stream": True,
        "max_tokens": plan.max_tokens,
        "messages": [{"role": "user", "content": BENCHMARK_PROMPTS[sequence % len(BENCHMARK_PROMPTS)]}],
    }


async def _worker(
    client: httpx.AsyncClient,
    url: str,
    headers: Mapping[str, str],
    plan: QosBenchmarkRequest,
    worker_index: int,
) -> None:
    for request_index in range(plan.requests_per_worker):
        try:
            await _send(
                client, url, headers, _request_body(plan, worker_index * plan.requests_per_worker + request_index)
            )
        except httpx.HTTPError as error:
            verbose_proxy_logger.warning("QoS benchmark request did not complete: %s", error)


def _level_headers(auth: Mapping[str, str], run_id: str, concurrency: int) -> Mapping[str, str]:
    return {**auth, "x-litellm-tags": f"{run_id},{level_tag(run_id, concurrency)}"}


async def run_benchmark(
    client: httpx.AsyncClient, base_url: str, api_key: str | None, run_id: str, plan: QosBenchmarkRequest
) -> None:
    url: Final = f"{base_url.rstrip('/')}/v1/chat/completions"
    auth: Final = {} if api_key is None else {"Authorization": f"Bearer {api_key}"}
    for concurrency in plan.concurrency:
        await asyncio.gather(
            *(
                _worker(client, url, _level_headers(auth, run_id, concurrency), plan, index)
                for index in range(concurrency)
            )
        )


async def _run_in_background(base_url: str, api_key: str | None, run_id: str, plan: QosBenchmarkRequest) -> None:
    limits: Final = httpx.Limits(max_connections=max(plan.concurrency), max_keepalive_connections=max(plan.concurrency))
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0), limits=limits) as client:
        await run_benchmark(client, base_url, api_key, run_id, plan)
    verbose_proxy_logger.info("QoS benchmark %s finished", run_id)


def start_benchmark(base_url: str, api_key: str | None, run_id: str, plan: QosBenchmarkRequest) -> None:
    task: Final = asyncio.create_task(_run_in_background(base_url, api_key, run_id, plan))
    _running.add(task)
    task.add_done_callback(_running.discard)
