"""Generate one short video per configured video deployment through the gateway, once or on a fixed schedule.

A deployment takes part when its model_info has a `qos_probe` object: {"image": bool, "params": {...}}. Every
deployment gets the same prompt, and the image-to-video ones also get the same first frame, a drawing of the scene
the prompt describes, so reviewers compare models on equal input. Each run submits to /v1/videos and polls
/v1/videos/{id} until the video ends, so the gateway records the submission and the final status with the
provider's queue time, run time and price for the 音视频 tab.
"""

import argparse
import logging
import math
import os
import struct
import time
import zlib
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import time as TimeOfDay
from itertools import accumulate, repeat
from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PROBE_PROMPT: Final = "固定镜头：阳光下的绿色草地上，一个红色皮球从画面左侧向右滚动，蓝天上飘着白云"
PROBE_TAG: Final = "qos-media-probe"
FIRST_FRAME_SIZE: Final = (1280, 720)
POLL_SECONDS: Final = 15
MAX_WAIT_SECONDS: Final = 8400
TERMINAL_STATUSES: Final = frozenset({"completed", "failed"})
LATE_LIMIT: Final = timedelta(minutes=10)
logger: Final = logging.getLogger("qos.media_probe")

ParamValue = str | int | float | bool
Color = tuple[int, ...]
Sleep = Callable[[float], None]
Now = Callable[[], datetime]

SKY_TOP: Final = (78, 140, 222)
SKY_HORIZON: Final = (182, 216, 246)
CLOUD: Final = (250, 251, 253)
GRASS_HORIZON: Final = (124, 192, 84)
GRASS_FRONT: Final = (52, 124, 42)
SHADOW: Final = (24, 60, 20)
BALL: Final = (208, 34, 38)
BALL_DARK: Final = (70, 8, 10)
HIGHLIGHT: Final = (255, 255, 255)


class ProbeSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

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


def mix(a: Color, b: Color, share: float) -> Color:
    weight: Final = min(max(share, 0.0), 1.0)
    return tuple(round(start + (end - start) * weight) for start, end in zip(a, b, strict=True))


def ellipse_reach(x: float, y: float, cx: float, cy: float, rx: float, ry: float) -> float:
    """0 at the centre of the ellipse, 1 on its edge."""
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2


def first_frame_png(width: int, height: int) -> bytes:
    """The opening frame of PROBE_PROMPT: a red ball on the left of a sunny lawn under a blue sky with clouds."""
    horizon: Final = round(height * 0.58)
    ball_x, ball_y, ball_r = width * 0.22, height * 0.75, height * 0.11
    clouds: Final = (
        (width * 0.62, height * 0.16, width * 0.09, height * 0.05),
        (width * 0.83, height * 0.27, width * 0.07, height * 0.04),
    )

    def pixel(x: int, y: int) -> Color:
        if math.hypot(x - ball_x, y - ball_y) <= ball_r:
            light: Final = math.hypot(x - (ball_x - 0.35 * ball_r), y - (ball_y - 0.4 * ball_r)) / (1.6 * ball_r)
            return mix(mix(BALL, BALL_DARK, light), HIGHLIGHT, 1 - light / 0.18)
        if y >= horizon:
            shadow: Final = ellipse_reach(
                x, y, ball_x + 0.25 * ball_r, ball_y + 0.97 * ball_r, 1.15 * ball_r, 0.22 * ball_r
            )
            grass: Final = mix(GRASS_HORIZON, GRASS_FRONT, (y - horizon) / (height - horizon))
            return mix(grass, SHADOW, 0.45 * (1 - shadow))
        cover: Final = max(2.5 * (1 - ellipse_reach(x, y, *cloud)) for cloud in clouds)
        return mix(mix(SKY_TOP, SKY_HORIZON, y / horizon), CLOUD, cover)

    def row(y: int) -> bytes:
        return b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header: Final = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels: Final = zlib.compress(b"".join(row(y) for y in range(height)), 6)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


def form_value(value: ParamValue) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def submit(client: httpx.Client, probe: Probe, first_frame: bytes) -> httpx.Response:
    if probe.spec.image:
        fields: Final = {key: form_value(value) for key, value in probe.spec.params.items()}
        return client.post(
            "/v1/videos",
            data={**fields, "model": probe.model, "prompt": PROBE_PROMPT},
            files={"input_reference": ("first_frame.png", first_frame, "image/png")},
        )
    return client.post("/v1/videos", json={**probe.spec.params, "model": probe.model, "prompt": PROBE_PROMPT})


def wait_for_end(client: httpx.Client, video_id: str, started: float, sleep: Sleep) -> str:
    while time.monotonic() - started < MAX_WAIT_SECONDS:
        sleep(POLL_SECONDS)
        polled: Final = client.get(f"/v1/videos/{video_id}")
        status: Final = VideoObject.model_validate_json(polled.content).status if polled.status_code == 200 else ""
        if status in TERMINAL_STATUSES:
            return status
    return f"no result after {MAX_WAIT_SECONDS} s"


def run_probe(client: httpx.Client, probe: Probe, first_frame: bytes, sleep: Sleep) -> Outcome:
    started: Final = time.monotonic()
    created: Final = submit(client, probe, first_frame)
    if created.status_code != 200:
        return Outcome(probe.model, f"submit failed {created.status_code}: {created.text[:160]}", 0.0)
    video: Final = VideoObject.model_validate_json(created.content)
    ended: Final = video.status in TERMINAL_STATUSES
    status: Final = video.status if ended else wait_for_end(client, video.id, started, sleep)
    return Outcome(probe.model, status, time.monotonic() - started)


def run_once(client: httpx.Client, dry_run: bool, sleep: Sleep) -> None:
    models: Final = TypeAdapter(ModelList).validate_json(client.get("/model/info").content)
    probes: Final = probes_from(models)
    logger.info("probing %d video models with the prompt %s", len(probes), PROBE_PROMPT)
    if dry_run:
        for probe in probes:
            logger.info("  %s: image=%s params=%s", probe.model, probe.spec.image, dict(probe.spec.params))
        return
    first_frame: Final = first_frame_png(*FIRST_FRAME_SIZE)
    with ThreadPoolExecutor(max_workers=max(len(probes), 1)) as pool:
        outcomes: Final = tuple(pool.map(lambda probe: run_probe(client, probe, first_frame, sleep), probes))
    for outcome in outcomes:
        logger.info("  %s: %s after %.0f s", outcome.model, outcome.status, outcome.seconds)


def daily_times(value: str) -> tuple[TimeOfDay, ...]:
    return tuple(sorted(TimeOfDay.fromisoformat(part.strip()) for part in value.split(",")))


def next_run(after: datetime, times: tuple[TimeOfDay, ...]) -> datetime:
    later_today: Final = tuple(run for run in (datetime.combine(after.date(), at) for at in times) if run > after)
    return later_today[0] if later_today else datetime.combine(after.date() + timedelta(days=1), times[0])


def runs_from(start: datetime, times: tuple[TimeOfDay, ...]) -> Iterator[datetime]:
    return accumulate(repeat(times), next_run, initial=next_run(start, times))


def on_time(run_at: datetime, sleep: Sleep, now: Now) -> bool:
    """Sleep until run_at a minute at a time, since one long sleep oversleeps by however long the machine slept."""
    while (left := (run_at - now()).total_seconds()) > 0:
        sleep(min(left, 60))
    return now() - run_at <= LATE_LIMIT


def scheduled_run(client: httpx.Client, run_at: datetime, dry_run: bool) -> None:
    logger.info("next run at %s", run_at.strftime("%Y-%m-%d %H:%M"))
    if on_time(run_at, time.sleep, datetime.now):
        run_once(client, dry_run, time.sleep)
        return
    logger.info("skipped the %s run, it is already %s", run_at.strftime("%H:%M"), datetime.now().strftime("%H:%M"))


def main() -> None:
    parser: Final = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000"))
    parser.add_argument(
        "--at", type=daily_times, default=(), help="daily run times in local time, such as 09:00,14:00; none runs once"
    )
    parser.add_argument("--dry-run", action="store_true", help="list the configured probes without sending anything")
    args: Final = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    headers: Final = {"Authorization": f"Bearer {os.environ['LITELLM_API_KEY']}", "x-litellm-tags": PROBE_TAG}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=120) as client:
        if not args.at:
            run_once(client, args.dry_run, time.sleep)
            return
        for run_at in runs_from(datetime.now(), args.at):
            scheduled_run(client, run_at, args.dry_run)


if __name__ == "__main__":
    main()
