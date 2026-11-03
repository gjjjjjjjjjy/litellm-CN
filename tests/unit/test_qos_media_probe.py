import importlib.util
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

import httpx
import pytest

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

    def __init__(self) -> None:
        self.created: dict[str, dict[str, bytes]] = {}
        self.polled: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/model/info":
            return httpx.Response(200, json=_MODEL_INFO)
        if request.method == "POST":
            fields: Final = _fields(request)
            model: Final = fields["model"].decode()
            self.created[model] = fields
            return httpx.Response(200, json={"id": f"video_{model}", "status": "queued"})
        status: Final = "completed" if request.url.path in self.polled else "in_progress"
        self.polled.append(request.url.path)
        return httpx.Response(200, json={"id": "video_without_its_deployment", "status": status})


def _probe_run() -> _Gateway:
    gateway: Final = _Gateway()
    with httpx.Client(transport=httpx.MockTransport(gateway.handle), base_url="http://gateway") as client:
        media_probe.run_once(client, dry_run=False, sleep=lambda seconds: None)
    return gateway


def test_every_probed_model_gets_the_same_prompt_and_every_image_model_the_same_first_frame() -> None:
    created: Final = _probe_run().created

    assert sorted(created) == sorted((*_IMAGE_MODELS, _TEXT_MODEL))
    assert {fields["prompt"].decode() for fields in created.values()} == {media_probe.PROBE_PROMPT}
    assert created[_IMAGE_MODELS[0]]["input_reference"] == created[_IMAGE_MODELS[1]]["input_reference"]
    assert "input_reference" not in created[_TEXT_MODEL]
    assert (created["LTX-2"]["num_frames"], created[_TEXT_MODEL]["seconds"]) == (b"73", b"4")


def test_every_poll_asks_about_the_id_the_video_was_created_under() -> None:
    polled: Final = _probe_run().polled

    assert sorted(polled) == sorted(f"/v1/videos/video_{model}" for model in (*_IMAGE_MODELS, _TEXT_MODEL) * 2)


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
