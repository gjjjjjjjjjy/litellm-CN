"""Generate one short video per configured video deployment through the gateway, once or on a fixed schedule.

A deployment takes part when its model_info has a `qos_probe` object: {"prompt": str, "image": bool, "params": {...}}.
Each run submits to /v1/videos and polls /v1/videos/{id} until the video ends, so the gateway records the
submission and the final status with the provider's queue time, run time and price for the 音视频 tab.
"""

import argparse
import logging
import os
import struct
import time
import zlib
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

DEFAULT_PROMPT: Final = "一只猫在阳光下的草地上慢慢走"
POLL_SECONDS: Final = 15
MAX_WAIT_SECONDS: Final = 3600
TERMINAL_STATUSES: Final = frozenset({"completed", "failed"})
logger: Final = logging.getLogger("qos.media_probe")

ParamValue = str | int | float | bool


class ProbeSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = DEFAULT_PROMPT
    image: bool = False
    params: Mapping[str, ParamValue] = Field(default_factory=lambda: {})  # mutable-ok: pydantic builds a fresh mapping


class ModelInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    mode: str | None = None
    qos_probe: ProbeSpec | None = None


class Deployment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    model_name: str
    model_info: ModelInfo = ModelInfo()


class ModelList(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    data: tuple[Deployment, ...]


class VideoObject(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    status: str


@dataclass(frozen=True, slots=True)
class Probe:
    model: str
    spec: ProbeSpec


@dataclass(frozen=True, slots=True)
class Outcome:
    model: str
    status: str
    seconds: float


def probes_from(models: ModelList) -> tuple[Probe, ...]:
    configured: Final = (d for d in models.data if d.model_info.mode == "video_generation")
    return tuple(Probe(d.model_name, d.model_info.qos_probe) for d in configured if d.model_info.qos_probe is not None)


def gradient_png(size: int) -> bytes:
    rows: Final = b"".join(
        b"\x00" + bytes(value for x in range(size) for value in (x, y, (x + y) // 2)) for y in range(size)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header: Final = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


def form_value(value: ParamValue) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def submit(client: httpx.Client, probe: Probe, image: bytes) -> httpx.Response:
    if probe.spec.image:
        fields: Final = {"model": probe.model, "prompt": probe.spec.prompt} | {
            key: form_value(value) for key, value in probe.spec.params.items()
        }
        return client.post("/v1/videos", data=fields, files={"input_reference": ("probe.png", image, "image/png")})
    return client.post("/v1/videos", json={"model": probe.model, "prompt": probe.spec.prompt, **probe.spec.params})


def run_probe(client: httpx.Client, probe: Probe, image: bytes) -> Outcome:
    started: Final = time.monotonic()
    created: Final = submit(client, probe, image)
    if created.status_code != 200:
        return Outcome(probe.model, f"submit failed {created.status_code}: {created.text[:160]}", 0.0)
    video: VideoObject = VideoObject.model_validate_json(created.content)
    while video.status not in TERMINAL_STATUSES and time.monotonic() - started < MAX_WAIT_SECONDS:
        time.sleep(POLL_SECONDS)
        polled = client.get(f"/v1/videos/{video.id}")
        if polled.status_code == 200:
            video = VideoObject.model_validate_json(polled.content)  # rebind-ok: the status advances each poll
    status: Final = video.status if video.status in TERMINAL_STATUSES else f"no result after {MAX_WAIT_SECONDS} s"
    return Outcome(probe.model, status, time.monotonic() - started)


def run_once(client: httpx.Client, dry_run: bool) -> None:
    models: Final = TypeAdapter(ModelList).validate_json(client.get("/model/info").content)
    probes: Final = probes_from(models)
    logger.info("probing %d video models", len(probes))
    if dry_run:
        for probe in probes:
            logger.info("  %s: image=%s params=%s", probe.model, probe.spec.image, dict(probe.spec.params))
        return
    image: Final = gradient_png(256)
    with ThreadPoolExecutor(max_workers=max(len(probes), 1)) as pool:
        outcomes: Final = tuple(pool.map(lambda probe: run_probe(client, probe, image), probes))
    for outcome in outcomes:
        logger.info("  %s: %s after %.0f s", outcome.model, outcome.status, outcome.seconds)


def next_slot(now: float, every_seconds: int) -> float:
    return (now // every_seconds + 1) * every_seconds


def sleep_until_next_run(every_seconds: int) -> None:
    wake_at: Final = next_slot(time.time(), every_seconds)
    logger.info("next run at %s", datetime.fromtimestamp(wake_at).strftime("%Y-%m-%d %H:%M:%S"))
    time.sleep(max(wake_at - time.time(), 0))


def main() -> None:
    parser: Final = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000"))
    parser.add_argument("--every", type=int, default=0, help="seconds between runs, aligned to the clock; 0 runs once")
    parser.add_argument("--dry-run", action="store_true", help="list the configured probes without sending anything")
    args: Final = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    headers: Final = {"Authorization": f"Bearer {os.environ['LITELLM_API_KEY']}"}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=120) as client:
        if args.every <= 0:
            run_once(client, args.dry_run)
            return
        while True:
            sleep_until_next_run(args.every)
            run_once(client, args.dry_run)


if __name__ == "__main__":
    main()
