"""Generate one short video per probed video deployment through the gateway and have a vision model rate each one,
at fixed times of day and whenever the gateway asks.

A deployment takes part when its model_info has a `qos_probe` object: {"image": bool, "params": {...}}. Every
deployment in a run gets the same prompt. With the scheduled prompt the image-to-video ones also get the same drawn
first frame; with any other prompt the text-to-video models go first and the image-to-video ones start from the
first frame of the first finished text-to-video video, so every model starts from the same picture. Each run submits
to /v1/videos and polls /v1/videos/{id} until the video ends, so the gateway records the submission and the final
status with the provider's queue time, run time and price for the 音视频 tab. Each finished video is then cut into
one still per second, which a vision model rates through the gateway, and the rating is stored on the video.

With --listen the gateway can also start a run with its own prompt (POST /evaluations) and ask for a new test prompt
(POST /prompts), authenticated with the gateway's master key.
"""

import argparse
import base64
import hmac
import io
import json
import logging
import math
import os
import re
import struct
import threading
import time
import zlib
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import time as TimeOfDay
from fractions import Fraction
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import accumulate, repeat
from typing import Annotated, Final

import av
import httpx
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, ValidationError

PROBE_PROMPT: Final = "固定镜头：阳光下的绿色草地上，一个红色皮球从画面左侧向右滚动，蓝天上飘着白云"
PROBE_TAG: Final = "qos-media-probe"
JUDGE_TAGS: Final = f"{PROBE_TAG},qos-video-judge"
FIRST_FRAME_SIZE: Final = (1280, 720)
POLL_SECONDS: Final = 15
MAX_WAIT_SECONDS: Final = 8400
JUDGE_TIMEOUT_SECONDS: Final = 330
DOWNLOAD_ATTEMPTS: Final = 3
DOWNLOAD_RETRY_SECONDS: Final = 10
PROMPT_TIMEOUT_SECONDS: Final = 170
STILL_QUALITY: Final = 90
TEXT_LIMIT: Final = 500
LIST_LIMIT: Final = 30
TERMINAL_STATUSES: Final = frozenset({"completed", "failed"})
LATE_LIMIT: Final = timedelta(minutes=10)
logger: Final = logging.getLogger("qos.media_probe")

ParamValue = str | int | float | bool
Color = tuple[int, ...]
Sleep = Callable[[float], None]
Now = Callable[[], datetime]
PromptText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TEXT_LIMIT)]

SKY_TOP: Final = (78, 140, 222)
SKY_HORIZON: Final = (182, 216, 246)
CLOUD: Final = (250, 251, 253)
GRASS_HORIZON: Final = (124, 192, 84)
GRASS_FRONT: Final = (52, 124, 42)
SHADOW: Final = (24, 60, 20)
BALL: Final = (208, 34, 38)
BALL_DARK: Final = (70, 8, 10)
HIGHLIGHT: Final = (255, 255, 255)

CRITERIA: Final = ("visual", "detail", "motion", "alignment", "physics")
JUDGE_SYSTEM: Final = """你是视频生成质量评审员。你会看到一条生成视频按每秒一帧截下的画面（按时间顺序），以及生成它用的 Prompt。只根据画面评分，不要猜测看不到的内容；帧与帧之间的变化反映运动。没有给你声音，不评声音。

每项按 1 到 5 分打分（1 很差，2 较差，3 一般，4 较好，5 很好）：
- visual（画质）：清晰度、噪点、模糊、色块、闪烁、变形等伪影
- detail（视频细节）：纹理、边缘、小物体、文字等细小结构是否清楚自然，有没有糊成一片，文字有没有写错
- motion（运动）：主体和镜头的运动是否连贯合理，有没有跳变，物体有没有突然出现、消失或变形
- alignment（Prompt 贴合度）：把 Prompt 拆成可以检查的要求（镜头、场景、主体、数量、颜色、文字、位置、动作和方向），逐条对照画面
- physics（物理常识）：重力、液体、碰撞、反射和倒影、阴影与光源方向、遮挡、大小和透视是否合理
- overall（总体）：综合以上各项

只输出一个 JSON 对象，不要输出其他文字：
{"overall": 分数, "visual": 分数, "detail": 分数, "motion": 分数, "alignment": 分数, "physics": 分数,
 "reasons": {"visual": "理由", "detail": "理由", "motion": "理由", "alignment": "理由", "physics": "理由"},
 "checklist": [{"requirement": "Prompt 里的一条要求", "met": true 或 false, "evidence": "第几秒看到了什么"}],
 "problems": [{"second": 第几秒, "problem": "具体问题"}]}"""
PROMPT_WRITER_SYSTEM: Final = """你为视频生成模型的质量测评写 Prompt。写一个新的中文 Prompt，让人看一条 4 秒左右的视频就能同时评判画质、视频细节、运动、Prompt 贴合度、物理常识和声音。要求：
- 一个具体的场景，开头就交代清楚画面里有什么、在哪里，第一帧就能看到主要物体
- 写明镜头是固定的还是怎样移动
- 至少一样考验细节的东西，例如文字、毛发、水珠或布料纹理
- 至少一个容易出错的物理现象，例如液体、碰撞、倒影或影子
- 写明颜色、数量、左右位置和运动方向，方便逐条核对
- 最后用「声音：」写出应该听到的声音
- 4 秒内能发生完，只有一个镜头，不要真实人物、品牌和敏感内容
- 不超过 150 字
只输出 Prompt 本身，不要标题、解释或引号。"""


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


class Check(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    requirement: str
    met: bool
    evidence: str = ""


class Problem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    second: float
    problem: str


class Verdict(BaseModel):
    """The judge's answer as it writes it; score_body trims it to what the gateway keeps."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    overall: int = Field(ge=1, le=5)
    visual: int = Field(ge=1, le=5)
    detail: int = Field(ge=1, le=5)
    motion: int = Field(ge=1, le=5)
    alignment: int = Field(ge=1, le=5)
    physics: int = Field(ge=1, le=5)
    reasons: Mapping[str, str] = Field(default_factory=lambda: {})  # mutable-ok: pydantic builds a fresh mapping
    checklist: tuple[Check, ...] = ()
    problems: tuple[Problem, ...] = ()


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    content: str | None = None


class ChatChoice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    message: ChatMessage


class ChatAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    choices: tuple[ChatChoice, ...] = Field(min_length=1)


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: PromptText


class PromptRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    avoid: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Probe:
    model: str
    spec: ProbeSpec


@dataclass(frozen=True, slots=True)
class Outcome:
    model: str
    status: str
    seconds: float
    video_id: str | None = None


@dataclass(frozen=True, slots=True)
class Stills:
    seconds: float
    fps: float
    width: int
    height: int
    jpegs: tuple[tuple[int, bytes], ...]


def probes_from(models: ModelList) -> tuple[Probe, ...]:
    configured: Final = (d for d in models.data if d.model_info.mode == "video_generation")
    return tuple(Probe(d.model_name, d.model_info.qos_probe) for d in configured if d.model_info.qos_probe is not None)


def listed_probes(client: httpx.Client) -> tuple[Probe, ...]:
    return probes_from(TypeAdapter(ModelList).validate_json(client.get("/model/info").raise_for_status().content))


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


def opening_frame_png(mp4: bytes) -> bytes:
    """The first frame of a video, scaled and cropped to FIRST_FRAME_SIZE, for image-to-video models to start from."""
    with av.open(io.BytesIO(mp4)) as container:
        image: Final = next(container.decode(container.streams.video[0])).to_image()
    width, height = FIRST_FRAME_SIZE
    scale: Final = max(width / image.width, height / image.height)
    resized: Final = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    left, top = (resized.width - width) // 2, (resized.height - height) // 2
    buffer: Final = io.BytesIO()
    resized.crop((left, top, left + width, top + height)).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg(image: Image.Image) -> bytes:
    buffer: Final = io.BytesIO()
    image.save(buffer, format="JPEG", quality=STILL_QUALITY)
    return buffer.getvalue()


def _duration(container_duration: int | None, stream_duration: int | None, time_base: Fraction | None) -> float:
    if container_duration:
        return container_duration / av.time_base
    return float(stream_duration * time_base) if stream_duration and time_base else 0.0


def stills_of(mp4: bytes) -> Stills:
    """The first frame at or after each whole second of a video, as JPEGs."""
    with av.open(io.BytesIO(mp4)) as container:
        stream: Final = container.streams.video[0]
        seconds: Final = _duration(container.duration, stream.duration, stream.time_base)
        picked: Final[dict[int, bytes]] = {}  # mutable-ok: filled while decoding so frames are not all kept in memory
        for frame in container.decode(stream):
            second = len(picked)
            if frame.time is not None and frame.time >= second - 1e-3 and (second < seconds or second == 0):
                picked[second] = _jpeg(frame.to_image())
        return Stills(
            seconds=round(seconds, 2),
            fps=float(stream.average_rate) if stream.average_rate else 0.0,
            width=stream.codec_context.width,
            height=stream.codec_context.height,
            jpegs=tuple(picked.items()),
        )


def form_value(value: ParamValue) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def submit(client: httpx.Client, probe: Probe, prompt: str, first_frame: bytes) -> httpx.Response:
    if probe.spec.image:
        fields: Final = {key: form_value(value) for key, value in probe.spec.params.items()}
        return client.post(
            "/v1/videos",
            data={**fields, "model": probe.model, "prompt": prompt},
            files={"input_reference": ("first_frame.png", first_frame, "image/png")},
        )
    return client.post("/v1/videos", json={**probe.spec.params, "model": probe.model, "prompt": prompt})


def wait_for_end(client: httpx.Client, video_id: str, started: float, sleep: Sleep) -> str:
    while time.monotonic() - started < MAX_WAIT_SECONDS:
        sleep(POLL_SECONDS)
        polled: Final = client.get(f"/v1/videos/{video_id}")
        status: Final = VideoObject.model_validate_json(polled.content).status if polled.status_code == 200 else ""
        if status in TERMINAL_STATUSES:
            return status
    return f"no result after {MAX_WAIT_SECONDS} s"


def _image_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


def judge_messages(prompt: str, image_to_video: bool, stills: Stills) -> list[dict[str, object]]:
    source: Final = (
        "这是图生视频，第 0 秒的画面是输入给模型的首帧，不是模型生成的，请重点看之后的画面。"
        if image_to_video
        else "这是文生视频，所有画面都是模型生成的。"
    )
    intro: Final = (
        f"Prompt：{prompt}\n{source}\n视频时长 {stills.seconds} 秒，每秒 {stills.fps:g} 帧，"
        f"分辨率 {stills.width}x{stills.height}。下面是每秒截一帧，共 {len(stills.jpegs)} 帧。"
    )
    frames: Final = [
        part
        for second, jpeg in stills.jpegs
        for part in (
            {"type": "text", "text": f"第 {second} 秒："},
            {"type": "image_url", "image_url": {"url": _image_url(jpeg)}},
        )
    ]
    return [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": [{"type": "text", "text": intro}, *frames]},
    ]


def answer_text(response: httpx.Response) -> str:
    return ChatAnswer.model_validate_json(response.raise_for_status().content).choices[0].message.content or ""


def verdict_from(text: str) -> Verdict:
    found: Final = re.search(r"\{.*\}", text, re.DOTALL)
    if found is None:
        raise ValueError(f"the judge answered without JSON: {text[:200]}")
    return Verdict.model_validate_json(found.group(0))


def score_body(verdict: Verdict, judge: str, frames: int) -> dict[str, object]:
    """The verdict in the shape the gateway keeps, cut to the lengths it accepts."""
    return {
        "judge": judge,
        "frames": frames,
        **{key: getattr(verdict, key) for key in ("overall", *CRITERIA)},
        "reasons": {key: verdict.reasons.get(key, "")[:TEXT_LIMIT] for key in CRITERIA},
        "checklist": [
            {"requirement": c.requirement[:TEXT_LIMIT], "met": c.met, "evidence": c.evidence[:TEXT_LIMIT]}
            for c in verdict.checklist[:LIST_LIMIT]
        ],
        "problems": [
            {"second": max(p.second, 0.0), "problem": p.problem[:TEXT_LIMIT]} for p in verdict.problems[:LIST_LIMIT]
        ],
    }


def video_bytes(client: httpx.Client, video_id: str, sleep: Sleep) -> bytes:
    """A finished video's MP4, fetched up to DOWNLOAD_ATTEMPTS times since the provider's file store fails a fetch now
    and then."""
    for _ in range(DOWNLOAD_ATTEMPTS - 1):
        try:
            fetched = client.get("/qos/videos/content", params={"video_id": video_id})
            if fetched.status_code == 200:
                return fetched.content
        except httpx.TransportError as error:
            logger.warning("fetching %s failed, trying again: %r", video_id, error)
        sleep(DOWNLOAD_RETRY_SECONDS)
    return client.get("/qos/videos/content", params={"video_id": video_id}).raise_for_status().content


def rate(client: httpx.Client, video_id: str, prompt: str, image_to_video: bool, judge: str, sleep: Sleep) -> str:
    """Have the judge rate a finished video from its stills and store the rating on it; a failure is only logged."""
    try:
        stills: Final = stills_of(video_bytes(client, video_id, sleep))
        answered: Final = client.post(
            "/v1/chat/completions",
            json={
                "model": judge,
                "temperature": 0,
                "max_tokens": 8192,
                "timeout": JUDGE_TIMEOUT_SECONDS - 30,
                "messages": judge_messages(prompt, image_to_video, stills),
            },
            headers={"x-litellm-tags": JUDGE_TAGS},
            timeout=JUDGE_TIMEOUT_SECONDS,
        )
        verdict: Final = verdict_from(answer_text(answered))
        client.put(
            "/qos/videos/evaluations/score",
            params={"video_id": video_id},
            json=score_body(verdict, judge, len(stills.jpegs)),
        ).raise_for_status()
        return f"rated {verdict.overall}/5 from {len(stills.jpegs)} stills"
    except (httpx.HTTPError, ValueError, OSError, av.FFmpegError) as error:
        logger.warning("could not rate %s: %r", video_id, error)
        return f"not rated: {error!r}"[:200]


def run_probe(
    client: httpx.Client, probe: Probe, prompt: str, first_frame: bytes, sleep: Sleep, judge: str | None
) -> Outcome:
    started: Final = time.monotonic()
    try:
        created: Final = submit(client, probe, prompt, first_frame)
        if created.status_code != 200:
            return Outcome(probe.model, f"submit failed {created.status_code}: {created.text[:160]}", 0.0)
        video: Final = VideoObject.model_validate_json(created.content)
        ended: Final = video.status in TERMINAL_STATUSES
        status: Final = video.status if ended else wait_for_end(client, video.id, started, sleep)
    except (httpx.HTTPError, ValidationError) as error:
        return Outcome(probe.model, f"gave up: {error!r}"[:200], time.monotonic() - started)
    rating: Final = (
        rate(client, video.id, prompt, probe.spec.image, judge, sleep) if judge and status == "completed" else ""
    )
    return Outcome(probe.model, f"{status} {rating}".strip(), time.monotonic() - started, video.id)


def _run_all(
    client: httpx.Client, probes: tuple[Probe, ...], prompt: str, first_frame: bytes, sleep: Sleep, judge: str | None
) -> tuple[Outcome, ...]:
    if not probes:
        return ()
    with ThreadPoolExecutor(max_workers=len(probes)) as pool:
        return tuple(pool.map(lambda probe: run_probe(client, probe, prompt, first_frame, sleep, judge), probes))


def evaluate(
    client: httpx.Client, prompt: str, probes: tuple[Probe, ...], sleep: Sleep, judge: str | None
) -> tuple[Outcome, ...]:
    """Run every probe on the prompt; image-to-video ones start from the drawn frame or a text-to-video first frame."""
    if prompt == PROBE_PROMPT:
        return _run_all(client, probes, prompt, first_frame_png(*FIRST_FRAME_SIZE), sleep, judge)
    image_probes: Final = tuple(probe for probe in probes if probe.spec.image)
    text_probes: Final = tuple(probe for probe in probes if not probe.spec.image)
    text_outcomes: Final = _run_all(client, text_probes, prompt, b"", sleep, judge)
    opening: Final = next((o.video_id for o in text_outcomes if o.video_id and o.status.startswith("completed")), None)
    if opening is None:
        return text_outcomes + _skipped(image_probes, "no finished text-to-video video to start from")
    try:
        frame: Final = opening_frame_png(video_bytes(client, opening, sleep))
    except (httpx.HTTPError, ValueError, OSError, av.FFmpegError) as error:
        return text_outcomes + _skipped(image_probes, f"could not take the first frame: {error!r}"[:160])
    return text_outcomes + _run_all(client, image_probes, prompt, frame, sleep, judge)


def _skipped(probes: tuple[Probe, ...], reason: str) -> tuple[Outcome, ...]:
    return tuple(Outcome(probe.model, f"skipped: {reason}", 0.0) for probe in probes)


def log_outcomes(prompt: str, outcomes: tuple[Outcome, ...]) -> None:
    logger.info("run with the prompt %s ended", prompt)
    for outcome in outcomes:
        logger.info("  %s: %s after %.0f s", outcome.model, outcome.status, outcome.seconds)


def run_once(client: httpx.Client, dry_run: bool, sleep: Sleep, judge: str | None) -> None:
    probes: Final = listed_probes(client)
    logger.info("probing %d video models with the prompt %s", len(probes), PROBE_PROMPT)
    if dry_run:
        for probe in probes:
            logger.info("  %s: image=%s params=%s", probe.model, probe.spec.image, dict(probe.spec.params))
        return
    log_outcomes(PROBE_PROMPT, evaluate(client, PROBE_PROMPT, probes, sleep, judge))


def start_evaluation(client: httpx.Client, judge: str | None, prompt: str) -> tuple[str, ...]:
    """Start a run with the prompt in the background and name the models it generates with."""
    probes: Final = listed_probes(client)
    logger.info("the gateway started a run of %d video models with the prompt %s", len(probes), prompt)

    def run() -> None:
        try:
            log_outcomes(prompt, evaluate(client, prompt, probes, time.sleep, judge))
        except (httpx.HTTPError, ValueError, OSError, av.FFmpegError) as error:
            logger.warning("the run with the prompt %s stopped: %r", prompt, error)

    threading.Thread(target=run, name="evaluation", daemon=True).start()
    return tuple(probe.model for probe in probes)


def write_prompt(client: httpx.Client, writer: str, avoid: tuple[str, ...]) -> str:
    """A new test prompt from the writer model, unlike the prompts to avoid."""
    recent: Final = "".join(f"\n- {used}" for used in avoid)
    answered: Final = client.post(
        "/v1/chat/completions",
        json={
            "model": writer,
            "temperature": 0.9,
            "max_tokens": 4096,
            "timeout": PROMPT_TIMEOUT_SECONDS - 20,
            "messages": [
                {"role": "system", "content": PROMPT_WRITER_SYSTEM},
                {"role": "user", "content": "写一个新的 Prompt。" + (f"不要和这些重复：{recent}" if recent else "")},
            ],
        },
        headers={"x-litellm-tags": JUDGE_TAGS},
        timeout=PROMPT_TIMEOUT_SECONDS,
    )
    written: Final = answer_text(answered).strip().strip("\"'“”`「」").strip()
    if not written:
        raise ValueError("the writer model answered with an empty prompt")
    return written[:TEXT_LIMIT]


def respond(
    path: str,
    authorization: str,
    body: bytes,
    api_key: str,
    start: Callable[[str], tuple[str, ...]],
    write: Callable[[tuple[str, ...]], str],
) -> tuple[int, dict[str, object]]:
    """What the probe answers the gateway: a started run or a new prompt."""
    if not hmac.compare_digest(authorization.encode(), f"Bearer {api_key}".encode()):
        return 401, {"error": "this needs the gateway's master key"}
    try:
        if path == "/evaluations":
            prompt: Final = EvaluationRequest.model_validate_json(body).prompt
            return 202, {"prompt": prompt, "models": list(start(prompt))}
        if path == "/prompts":
            return 200, {"prompt": write(PromptRequest.model_validate_json(body or b"{}").avoid)}
    except ValidationError as error:
        return 400, {"error": str(error)}
    except (httpx.HTTPError, ValueError) as error:
        return 502, {"error": repr(error)}
    return 404, {"error": f"nothing at {path}"}


def serve(port: int, answer: Callable[[str, str, bytes], tuple[int, dict[str, object]]]) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body: Final = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            status, payload = answer(self.path, self.headers.get("Authorization", ""), body)
            encoded: Final = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:
            logger.info("gateway asked: %s", format % args)

    server: Final = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, name="api", daemon=True).start()
    logger.info("answering the gateway on port %d", port)
    return server


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


def scheduled_run(client: httpx.Client, run_at: datetime, dry_run: bool, judge: str | None) -> None:
    logger.info("next run at %s", run_at.strftime("%Y-%m-%d %H:%M"))
    if on_time(run_at, time.sleep, datetime.now):
        run_once(client, dry_run, time.sleep, judge)
        return
    logger.info("skipped the %s run, it is already %s", run_at.strftime("%H:%M"), datetime.now().strftime("%H:%M"))


def main() -> None:
    parser: Final = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000"))
    parser.add_argument(
        "--at", type=daily_times, default=(), help="daily run times in local time, such as 09:00,14:00; none runs once"
    )
    parser.add_argument("--listen", type=int, default=0, help="port the gateway starts runs on; 0 turns it off")
    parser.add_argument(
        "--judge-model", default="qwen3.8-27b", help="vision model that rates stills and writes prompts; empty skips"
    )
    parser.add_argument("--dry-run", action="store_true", help="list the configured probes without sending anything")
    args: Final = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    api_key: Final = os.environ["LITELLM_API_KEY"]
    judge: Final = args.judge_model or None
    headers: Final = {"Authorization": f"Bearer {api_key}", "x-litellm-tags": PROBE_TAG}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=120) as client:
        if args.listen:
            serve(
                args.listen,
                partial(
                    respond,
                    api_key=api_key,
                    start=partial(start_evaluation, client, judge),
                    write=partial(write_prompt, client, args.judge_model),
                ),
            )
        if not args.at:
            if args.listen:
                threading.Event().wait()
            run_once(client, args.dry_run, time.sleep, judge)
            return
        for run_at in runs_from(datetime.now(), args.at):
            scheduled_run(client, run_at, args.dry_run, judge)


if __name__ == "__main__":
    main()
