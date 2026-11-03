import base64
import importlib.util
import io
import json
import struct
import zlib
from collections.abc import Iterator
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import HTTP
from itertools import islice
from pathlib import Path
from typing import Final

import av
import httpx
import pytest
from PIL import Image

ROOT: Final = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("media_probe", ROOT / "qos" / "media_probe.py")
assert _spec is not None and _spec.loader is not None
media_probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(media_probe)

_IMAGE_MODELS: Final = ("LTX-2", "Wan2_2-I2V-A14B")
_TEXT_MODEL: Final = "MiniMax-H3"
_MODEL_INFO: Final = {
    "data": [
        {
            "model_name": "LTX-2",
            "model_info": {"mode": "video_generation", "qos_probe": {"image": True, "params": {"num_frames": 73}}},
        },
        {"model_name": "Wan2_2-I2V-A14B", "model_info": {"mode": "video_generation", "qos_probe": {"image": True}}},
        {
            "model_name": _TEXT_MODEL,
            "model_info": {
                "mode": "video_generation",
                "qos_probe": {"params": {"seconds": "4", "prompt": "a model's own prompt"}},
            },
        },
        {"model_name": "Unprobed-Video", "model_info": {"mode": "video_generation"}},
        {"model_name": "IndexTTS-2", "model_info": {"mode": "audio_speech", "qos_probe": {}}},
    ]
}
_RED: Final = (220, 20, 20)
_GREEN: Final = (20, 200, 20)
_BLUE: Final = (20, 20, 220)
_WHITE: Final = (240, 240, 240)
_STREET: Final = "夜晚刚下过雨的街道，镜头从左向右缓慢平移，一个穿黄色雨衣的人骑着自行车从画面左侧骑向右侧"
_VERDICT: Final = {
    "overall": 3,
    "visual": 4,
    "detail": 2,
    "motion": 3,
    "alignment": 4,
    "physics": 2,
    "reasons": {"detail": "招牌上的字糊了", "physics": "积水里没有倒影", "audio": "听不到"},
    "checklist": [{"requirement": "骑车人从左向右", "met": True, "evidence": "第 1 到 3 秒一路向右"}],
    "problems": [{"second": 2, "problem": "车轮变形"}],
}


def _mp4(colors: tuple[tuple[int, int, int], ...], fps: int) -> bytes:
    """A small video showing one solid color per frame."""
    buffer: Final = io.BytesIO()
    with av.open(buffer, mode="w", format="mp4") as container:
        stream = container.add_stream("mpeg4", rate=fps)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        for color in colors:
            container.mux(stream.encode(av.VideoFrame.from_image(Image.new("RGB", (64, 48), color))))
        container.mux(stream.encode())
    return buffer.getvalue()


_A_COLOR_A_SECOND: Final = _mp4((_RED,) * 4 + (_GREEN,) * 4 + (_BLUE,) * 4 + (_WHITE,) * 2, fps=4)


def _dominant(image: Image.Image) -> str:
    red, green, blue = image.convert("RGB").resize((1, 1)).getpixel((0, 0))
    if min(red, green, blue) > 180:
        return "white"
    return ("red", "green", "blue")[max(range(3), key=lambda channel: (red, green, blue)[channel])]


def _fields(request: httpx.Request) -> dict[str, bytes]:
    content_type: Final = request.headers["content-type"]
    if content_type == "application/json":
        return {key: str(value).encode() for key, value in json.loads(request.content).items()}
    form: Final = BytesParser(policy=HTTP).parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode() + request.content
    )
    assert isinstance(form, EmailMessage)
    return {
        str(part.get_param("name", header="content-disposition")): part.get_payload(decode=True)
        for part in form.iter_parts()
    }


class _Gateway:
    """Answers the probe like the gateway, except a status names another id, as the gateway once did."""

    def __init__(self, judge_answer: str = json.dumps(_VERDICT, ensure_ascii=False), content_failures: int = 0) -> None:
        self.judge_answer = judge_answer
        self.content_failures = content_failures
        self.created: dict[str, dict[str, bytes]] = {}
        self.events: list[str] = []
        self.polled: list[str] = []
        self.judged: list[dict[str, object]] = []
        self.scores: dict[str, dict[str, object]] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:
        path: Final = request.url.path
        if path == "/model/info":
            return httpx.Response(200, json=_MODEL_INFO)
        if path == "/qos/videos/content":
            self.content_failures -= 1
            return (
                httpx.Response(502, json={"detail": "the file store failed"})
                if self.content_failures >= 0
                else httpx.Response(200, content=_A_COLOR_A_SECOND)
            )
        if path == "/v1/chat/completions":
            self.judged.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": self.judge_answer}}]})
        if path == "/qos/videos/evaluations/score":
            self.scores[request.url.params["video_id"]] = json.loads(request.content)
            return httpx.Response(200, json={})
        if request.method == "POST":
            fields: Final = _fields(request)
            model: Final = fields["model"].decode()
            self.created[model] = fields
            self.events.append(f"submitted {model}")
            return httpx.Response(200, json={"id": f"video_{model}", "status": "queued"})
        done: Final = path in self.polled
        self.polled.append(path)
        if done:
            self.events.append(f"finished {path.rsplit('_', 1)[-1]}")
        return httpx.Response(
            200, json={"id": "video_without_its_deployment", "status": "completed" if done else "in_progress"}
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle), base_url="http://gateway")


def _probe_run(gateway: _Gateway, judge: str | None = None) -> _Gateway:
    with gateway.client() as client:
        media_probe.run_once(client, dry_run=False, sleep=lambda seconds: None, judge=judge)
    return gateway


def test_every_probed_model_gets_the_same_prompt_and_every_image_model_the_same_first_frame() -> None:
    created: Final = _probe_run(_Gateway()).created

    assert sorted(created) == sorted((*_IMAGE_MODELS, _TEXT_MODEL))
    assert {fields["prompt"].decode() for fields in created.values()} == {media_probe.PROBE_PROMPT}
    assert created[_IMAGE_MODELS[0]]["input_reference"] == created[_IMAGE_MODELS[1]]["input_reference"]
    assert "input_reference" not in created[_TEXT_MODEL]
    assert (created["LTX-2"]["num_frames"], created[_TEXT_MODEL]["seconds"]) == (b"73", b"4")


def test_every_poll_asks_about_the_id_the_video_was_created_under() -> None:
    polled: Final = _probe_run(_Gateway()).polled

    assert sorted(polled) == sorted(f"/v1/videos/video_{model}" for model in (*_IMAGE_MODELS, _TEXT_MODEL) * 2)


def test_any_other_prompt_starts_the_image_models_from_the_text_models_first_frame() -> None:
    gateway: Final = _Gateway()

    with gateway.client() as client:
        outcomes: Final = media_probe.evaluate(client, _STREET, media_probe.listed_probes(client), lambda _: None, None)

    assert gateway.events[:2] == [f"submitted {_TEXT_MODEL}", f"finished {_TEXT_MODEL}"]
    assert {fields["prompt"].decode() for fields in gateway.created.values()} == {_STREET}
    first_frames: Final = tuple(
        Image.open(io.BytesIO(gateway.created[model]["input_reference"])) for model in _IMAGE_MODELS
    )
    assert {(frame.size, _dominant(frame)) for frame in first_frames} == {(media_probe.FIRST_FRAME_SIZE, "red")}
    assert sorted(outcome.status for outcome in outcomes) == ["completed"] * 3


def test_with_no_finished_text_video_the_image_models_are_skipped_rather_than_given_a_wrong_frame() -> None:
    gateway: Final = _Gateway()
    image_only: Final = tuple(
        probe
        for probe in media_probe.probes_from(media_probe.ModelList.model_validate(_MODEL_INFO))
        if probe.spec.image
    )

    with gateway.client() as client:
        outcomes: Final = media_probe.evaluate(client, _STREET, image_only, lambda _: None, None)

    assert gateway.created == {}
    assert {outcome.status for outcome in outcomes} == {"skipped: no finished text-to-video video to start from"}


def test_a_failed_fetch_of_the_text_video_is_tried_again_before_the_image_models_start() -> None:
    gateway: Final = _Gateway(content_failures=1)
    naps: Final[list[float]] = []

    with gateway.client() as client:
        outcomes: Final = media_probe.evaluate(client, _STREET, media_probe.listed_probes(client), naps.append, None)

    assert media_probe.DOWNLOAD_RETRY_SECONDS in naps
    assert sorted(gateway.created) == sorted((*_IMAGE_MODELS, _TEXT_MODEL))
    assert sorted(outcome.status for outcome in outcomes) == ["completed"] * 3


def test_when_the_text_video_cannot_be_fetched_the_image_models_are_skipped_and_the_run_still_ends() -> None:
    gateway: Final = _Gateway(content_failures=media_probe.DOWNLOAD_ATTEMPTS)

    with gateway.client() as client:
        outcomes: Final = media_probe.evaluate(client, _STREET, media_probe.listed_probes(client), lambda _: None, None)

    assert sorted(gateway.created) == [_TEXT_MODEL]
    image_statuses: Final = [outcome.status for outcome in outcomes if outcome.model in _IMAGE_MODELS]
    assert len(image_statuses) == len(_IMAGE_MODELS)
    assert all(status.startswith("skipped: could not take the first frame") for status in image_statuses)


def test_the_stills_are_the_first_frame_at_or_after_each_whole_second() -> None:
    stills: Final = media_probe.stills_of(_A_COLOR_A_SECOND)

    assert (stills.seconds, stills.fps, [second for second, _ in stills.jpegs]) == (3.5, 4.0, [0, 1, 2, 3])
    assert [_dominant(Image.open(io.BytesIO(jpeg))) for _, jpeg in stills.jpegs] == ["red", "green", "blue", "white"]


def test_each_finished_video_is_rated_from_its_stills_and_the_rating_kept_on_it() -> None:
    gateway: Final = _probe_run(_Gateway(), judge="qwen-test")

    assert sorted(gateway.scores) == sorted(f"video_{model}" for model in (*_IMAGE_MODELS, _TEXT_MODEL))
    assert gateway.scores[f"video_{_TEXT_MODEL}"] == {
        "judge": "qwen-test",
        "frames": 4,
        "overall": 3,
        "visual": 4,
        "detail": 2,
        "motion": 3,
        "alignment": 4,
        "physics": 2,
        "reasons": {
            "visual": "",
            "detail": "招牌上的字糊了",
            "motion": "",
            "alignment": "",
            "physics": "积水里没有倒影",
        },
        "checklist": [{"requirement": "骑车人从左向右", "met": True, "evidence": "第 1 到 3 秒一路向右"}],
        "problems": [{"second": 2.0, "problem": "车轮变形"}],
    }
    asked: Final = {request["model"] for request in gateway.judged}
    assert asked == {"qwen-test"}
    user_parts: Final = [request["messages"][1]["content"] for request in gateway.judged]
    labels: Final = {tuple(part["text"] for part in parts[1:] if part["type"] == "text") for parts in user_parts}
    assert labels == {("第 0 秒：", "第 1 秒：", "第 2 秒：", "第 3 秒：")}
    intros: Final = sorted(parts[0]["text"] for parts in user_parts)
    assert sum("第 0 秒的画面是输入给模型的首帧" in intro for intro in intros) == len(_IMAGE_MODELS)


def test_a_judge_answer_without_json_leaves_the_video_unrated_without_stopping_the_run() -> None:
    gateway: Final = _Gateway(judge_answer="这条视频总体不错")

    with gateway.client() as client:
        outcomes: Final = media_probe.evaluate(
            client, media_probe.PROBE_PROMPT, media_probe.listed_probes(client), lambda _: None, "qwen-test"
        )

    assert gateway.scores == {}
    assert len(outcomes) == 3
    assert all(outcome.status.startswith("completed not rated") for outcome in outcomes)


def _respond(path: str, authorization: str, body: bytes, started: list[str]) -> tuple[int, dict[str, object]]:
    def start(prompt: str) -> tuple[str, ...]:
        started.append(prompt)
        return (_TEXT_MODEL, *_IMAGE_MODELS)

    def write(avoid: tuple[str, ...]) -> str:
        if avoid == ("broken",):
            raise httpx.ConnectError("writer unreachable")
        return f"a prompt unlike {len(avoid)} others"

    return media_probe.respond(path, authorization, body, api_key="sk-master", start=start, write=write)


@pytest.mark.parametrize(
    ("path", "authorization", "body", "status", "payload"),
    (
        (
            "/evaluations",
            "Bearer sk-master",
            json.dumps({"prompt": f" {_STREET} "}).encode(),
            202,
            {"prompt": _STREET, "models": [_TEXT_MODEL, *_IMAGE_MODELS]},
        ),
        ("/evaluations", "Bearer sk-someone-else", json.dumps({"prompt": _STREET}).encode(), 401, None),
        ("/evaluations", "", json.dumps({"prompt": _STREET}).encode(), 401, None),
        ("/evaluations", "Bearer sk-master", json.dumps({"prompt": "  "}).encode(), 400, None),
        (
            "/prompts",
            "Bearer sk-master",
            json.dumps({"avoid": ["a", "b"]}).encode(),
            200,
            {"prompt": "a prompt unlike 2 others"},
        ),
        ("/prompts", "Bearer sk-master", json.dumps({"avoid": ["broken"]}).encode(), 502, None),
        ("/elsewhere", "Bearer sk-master", b"{}", 404, None),
    ),
)
def test_the_probe_answers_only_the_gateway_and_only_for_runs_and_prompts(
    path: str, authorization: str, body: bytes, status: int, payload: dict[str, object] | None
) -> None:
    started: Final[list[str]] = []

    answered_status, answered = _respond(path, authorization, body, started)

    assert answered_status == status
    if payload is not None:
        assert answered == payload
    assert started == ([_STREET] if status == 202 else [])


def test_a_new_prompt_is_asked_for_unlike_the_recent_ones_and_comes_back_without_quotes() -> None:
    asked: Final[list[dict[str, object]]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": f"“{_STREET}”\n"}}]})

    with httpx.Client(transport=httpx.MockTransport(handle), base_url="http://gateway") as client:
        written: Final = media_probe.write_prompt(client, "qwen-test", ("红球滚过草地", "倒茶"))

    assert written == _STREET
    ((request,),) = (asked,)
    assert request["model"] == "qwen-test"
    assert "- 红球滚过草地\n- 倒茶" in request["messages"][1]["content"]


def _chunks(png: bytes, offset: int = 8) -> Iterator[tuple[bytes, bytes]]:
    if offset >= len(png):
        return
    (length,) = struct.unpack_from(">I", png, offset)
    yield png[offset + 4 : offset + 8], png[offset + 8 : offset + 8 + length]
    yield from _chunks(png, offset + 12 + length)


def _rgb_rows(png: bytes, width: int) -> tuple[tuple[tuple[int, ...], ...], ...]:
    stride: Final = 1 + 3 * width
    raw: Final = zlib.decompress(b"".join(data for kind, data in _chunks(png) if kind == b"IDAT"))
    rows: Final = tuple(raw[start : start + stride] for start in range(0, len(raw), stride))
    assert {row[0] for row in rows} == {0}, "the probe writes unfiltered rows"
    return tuple(tuple(tuple(row[1 + 3 * x : 4 + 3 * x]) for x in range(width)) for row in rows)


def test_the_first_frame_shows_what_the_prompt_opens_on_a_red_ball_on_the_left_of_a_lawn_under_a_blue_sky() -> None:
    width, height = 320, 180
    rows: Final = _rgb_rows(media_probe.first_frame_png(width, height), width)
    red: Final = tuple((x, y) for y, row in enumerate(rows) for x, (r, g, b) in enumerate(row) if r > 2 * max(g, b))

    assert len(rows) == height
    assert all(b > g > r for r, g, b in rows[0]), "blue sky along the top"
    assert all(g > r and g > b for r, g, b in rows[-1]), "green grass along the bottom"
    assert sum(x for x, _ in red) / len(red) < width / 3, "the ball starts on the left so it can roll right"
    assert sum(y for _, y in red) / len(red) > height / 2, "the ball sits on the grass"


_RUN_TIMES: Final = media_probe.daily_times("17:00, 09:00,11:30,14:00")


@pytest.mark.parametrize(
    ("now", "expected"),
    (
        (datetime(2026, 11, 3, 8, 0), datetime(2026, 11, 3, 9, 0)),
        (datetime(2026, 11, 3, 9, 0), datetime(2026, 11, 3, 11, 30)),
        (datetime(2026, 11, 3, 15, 12), datetime(2026, 11, 3, 17, 0)),
        (datetime(2026, 11, 3, 17, 0, 1), datetime(2026, 11, 4, 9, 0)),
    ),
)
def test_the_next_run_is_the_first_daily_time_after_now(now: datetime, expected: datetime) -> None:
    assert media_probe.next_run(now, _RUN_TIMES) == expected


def test_runs_follow_the_daily_times_into_the_next_day() -> None:
    runs: Final = islice(media_probe.runs_from(datetime(2026, 11, 3, 15, 0), _RUN_TIMES), 5)

    assert [run.strftime("%m-%d %H:%M") for run in runs] == [
        "11-03 17:00",
        "11-04 09:00",
        "11-04 11:30",
        "11-04 14:00",
        "11-04 17:00",
    ]


class _Clock:
    """Wall-clock time that a nap moves forward, plus however long the machine slept during the first nap."""

    def __init__(self, start: datetime, slept_through: timedelta = timedelta()) -> None:
        self.now = start
        self.slept_through = slept_through
        self.naps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds) + (self.slept_through if not self.naps else timedelta())
        self.naps.append(seconds)

    def read(self) -> datetime:
        return self.now


def test_a_run_starts_on_time_after_waiting_a_minute_at_a_time() -> None:
    clock: Final = _Clock(datetime(2026, 11, 3, 13, 57, 30))

    assert media_probe.on_time(datetime(2026, 11, 3, 14, 0), clock.sleep, clock.read)
    assert clock.naps == [60, 60, 30]


def test_a_run_the_machine_slept_through_is_skipped_instead_of_started_late() -> None:
    clock: Final = _Clock(datetime(2026, 11, 3, 11, 0), slept_through=timedelta(hours=2))

    assert not media_probe.on_time(datetime(2026, 11, 3, 11, 30), clock.sleep, clock.read)
    assert clock.naps == [60]


@pytest.mark.parametrize(("late", "runs"), ((timedelta(minutes=9), True), (timedelta(minutes=11), False)))
def test_a_run_still_starts_a_few_minutes_late_but_not_once_its_time_is_long_gone(late: timedelta, runs: bool) -> None:
    run_at: Final = datetime(2026, 11, 3, 11, 30)
    clock: Final = _Clock(run_at + late)

    assert media_probe.on_time(run_at, clock.sleep, clock.read) is runs
    assert clock.naps == []


def test_a_judge_still_is_sent_as_a_jpeg_data_url() -> None:
    url: Final = media_probe.judge_messages(_STREET, False, media_probe.stills_of(_A_COLOR_A_SECOND))[1]["content"][2][
        "image_url"
    ]["url"]

    assert url.startswith("data:image/jpeg;base64,")
    assert _dominant(Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))) == "red"
