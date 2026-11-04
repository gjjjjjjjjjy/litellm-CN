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
        {
            "model_name": "IndexTTS-2",
            "model_info": {
                "mode": "audio_speech",
                "qos_probe": {"params": {"prompt_audio_url": "https://voice/a.wav"}},
            },
        },
        {"model_name": "IndexTTS-2", "model_info": {"mode": "audio_speech", "qos_probe": {}}},
        {"model_name": "Broken-TTS", "model_info": {"mode": "audio_speech", "qos_probe": {}}},
        {
            "model_name": "SenseVoiceSmall",
            "model_info": {"mode": "audio_transcription", "qos_probe": {"params": {"language": "zh"}}},
        },
        {"model_name": "Unprobed-ASR", "model_info": {"mode": "audio_transcription"}},
    ]
}
_SPEECH_MODELS: Final = ("IndexTTS-2", "Broken-TTS")
_TRANSCRIPTION_MODEL: Final = "SenseVoiceSmall"
_WAV: Final = b"RIFF\x24\x00\x00\x00WAVEfmt "
_HEARD: Final = "今天天气很好，我们一起去公园散步，顺便买写水果回家。"
_RUN: Final = media_probe.Run("20261104-101200-abc123", scheduled=False)
_NO_SPEECH: Final = media_probe.SpeechKit(Path("/nonexistent"), None)
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

    def __init__(
        self,
        judge_answer: str = json.dumps(_VERDICT, ensure_ascii=False),
        content_failures: int = 0,
        unlogged_transcripts: int = 1,
    ) -> None:
        self.judge_answer = judge_answer
        self.content_failures = content_failures
        self.unlogged_transcripts = unlogged_transcripts
        self.created: dict[str, dict[str, bytes]] = {}
        self.events: list[str] = []
        self.polled: list[str] = []
        self.judged: list[dict[str, object]] = []
        self.scores: dict[str, dict[str, object]] = {}
        self.spoken: list[dict[str, object]] = []
        self.heard: dict[str, dict[str, bytes]] = {}
        self.transcripts: dict[str, dict[str, object]] = {}
        self.runs: dict[str, dict[str, object]] = {}

    def _speech(self, request: httpx.Request) -> httpx.Response | None:
        path: Final = request.url.path
        if path == "/v1/audio/speech":
            body: Final = json.loads(request.content)
            self.spoken.append(body)
            self.runs[f"speech {body['model']}"] = json.loads(request.headers[media_probe.RUN_METADATA_HEADER])
            if body["model"] == "Broken-TTS":
                return httpx.Response(400, json={"error": "the resource pack does not cover this model"})
            return httpx.Response(200, content=_WAV, headers={"x-litellm-call-id": f"call-{body['model']}"})
        if path == "/v1/audio/transcriptions":
            fields: Final = _fields(request)
            model: Final = fields["model"].decode()
            self.heard[model] = fields
            self.runs[f"transcription {model}"] = json.loads(request.headers[media_probe.RUN_METADATA_HEADER])
            return httpx.Response(200, json={"text": _HEARD}, headers={"x-litellm-call-id": f"call-{model}"})
        if path == "/qos/speech/evaluations/transcript":
            self.unlogged_transcripts -= 1
            if self.unlogged_transcripts >= 0:
                return httpx.Response(404, json={"detail": "not logged yet"})
            self.transcripts[request.url.params["request_id"]] = json.loads(request.content)
            return httpx.Response(200, json={})
        return None

    def handle(self, request: httpx.Request) -> httpx.Response:
        path: Final = request.url.path
        if path == "/model/info":
            return httpx.Response(200, json=_MODEL_INFO)
        speech: Final = self._speech(request)
        if speech is not None:
            return speech
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
            self.runs[f"video {model}"] = json.loads(request.headers[media_probe.RUN_METADATA_HEADER])
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


def _probe_run(gateway: _Gateway, judge: str | None = None, kit: media_probe.SpeechKit = _NO_SPEECH) -> _Gateway:
    with gateway.client() as client:
        media_probe.run_once(client, dry_run=False, sleep=lambda seconds: None, judge=judge, kit=kit)
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
        outcomes: Final = media_probe.evaluate(
            client, _STREET, media_probe.listed_probes(client), lambda _: None, None, _RUN
        )

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
        outcomes: Final = media_probe.evaluate(client, _STREET, image_only, lambda _: None, None, _RUN)

    assert gateway.created == {}
    assert {outcome.status for outcome in outcomes} == {"skipped: no finished text-to-video video to start from"}


def test_a_failed_fetch_of_the_text_video_is_tried_again_before_the_image_models_start() -> None:
    gateway: Final = _Gateway(content_failures=1)
    naps: Final[list[float]] = []

    with gateway.client() as client:
        outcomes: Final = media_probe.evaluate(
            client, _STREET, media_probe.listed_probes(client), naps.append, None, _RUN
        )

    assert media_probe.DOWNLOAD_RETRY_SECONDS in naps
    assert sorted(gateway.created) == sorted((*_IMAGE_MODELS, _TEXT_MODEL))
    assert sorted(outcome.status for outcome in outcomes) == ["completed"] * 3


def test_when_the_text_video_cannot_be_fetched_the_image_models_are_skipped_and_the_run_still_ends() -> None:
    gateway: Final = _Gateway(content_failures=media_probe.DOWNLOAD_ATTEMPTS)

    with gateway.client() as client:
        outcomes: Final = media_probe.evaluate(
            client, _STREET, media_probe.listed_probes(client), lambda _: None, None, _RUN
        )

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
            client, media_probe.PROBE_PROMPT, media_probe.listed_probes(client), lambda _: None, "qwen-test", _RUN
        )

    assert gateway.scores == {}
    assert len(outcomes) == 3
    assert all(outcome.status.startswith("completed not rated") for outcome in outcomes)


def _respond(path: str, authorization: str, body: bytes, started: list[str]) -> tuple[int, dict[str, object]]:
    def start(prompt: str) -> tuple[str, ...]:
        started.append(prompt)
        return (_TEXT_MODEL, *_IMAGE_MODELS)

    def start_speech() -> tuple[str, ...]:
        started.append("speech")
        return ("IndexTTS-2", _TRANSCRIPTION_MODEL)

    def write(avoid: tuple[str, ...]) -> str:
        if avoid == ("broken",):
            raise httpx.ConnectError("writer unreachable")
        return f"a prompt unlike {len(avoid)} others"

    return media_probe.respond(
        path, authorization, body, api_key="sk-master", start=start, start_speech=start_speech, write=write
    )


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
        ("/speech-evaluations", "Bearer sk-master", b"", 202, {"models": ["IndexTTS-2", _TRANSCRIPTION_MODEL]}),
        ("/speech-evaluations", "Bearer sk-someone-else", b"", 401, None),
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
    assert started == ([] if status != 202 else ["speech"] if path == "/speech-evaluations" else [_STREET])


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


def _speech_run(gateway: _Gateway, kit: media_probe.SpeechKit, naps: list[float]) -> dict[str, str]:
    with gateway.client() as client:
        probes: Final = media_probe.speech_probes_from(media_probe.listed_models(client))
        outcomes: Final = media_probe.evaluate_speech(client, probes, _RUN, kit, naps.append)
    return {outcome.model: outcome.status for outcome in outcomes}


def test_a_scheduled_run_names_itself_on_every_video_speech_and_transcription_request(tmp_path: Path) -> None:
    runs: Final = _probe_run(_Gateway(), kit=media_probe.SpeechKit(tmp_path, _WAV)).runs

    assert sorted(runs) == sorted(
        (
            *(f"video {model}" for model in (*_IMAGE_MODELS, _TEXT_MODEL)),
            *(f"speech {model}" for model in _SPEECH_MODELS),
            f"transcription {_TRANSCRIPTION_MODEL}",
        )
    )
    assert len({run["qos_probe_run"] for run in runs.values()}) == 1
    assert {run["qos_probe_scheduled"] for run in runs.values()} == {True}
    assert {run.get("qos_probe_text") for key, run in runs.items() if not key.startswith("video")} == {
        media_probe.SPEECH_TEXT
    }


def test_every_speech_model_group_reads_the_sentence_once_and_its_audio_is_kept_under_the_gateways_id(
    tmp_path: Path,
) -> None:
    gateway: Final = _Gateway()

    statuses: Final = _speech_run(gateway, media_probe.SpeechKit(tmp_path, _WAV), [])

    assert sorted(body["model"] for body in gateway.spoken) == sorted(_SPEECH_MODELS)
    assert {body["input"] for body in gateway.spoken} == {media_probe.SPEECH_TEXT}
    (index_tts,) = (body for body in gateway.spoken if body["model"] == "IndexTTS-2")
    assert index_tts["prompt_audio_url"] == "https://voice/a.wav"
    assert [(path.name, path.read_bytes()) for path in tmp_path.iterdir()] == [("call-IndexTTS-2", _WAV)]
    assert statuses["IndexTTS-2"] == "spoke"
    assert statuses["Broken-TTS"].startswith("failed 400")


def test_a_transcription_model_hears_the_recording_and_what_it_heard_is_kept_once_the_gateway_logged_it(
    tmp_path: Path,
) -> None:
    gateway: Final = _Gateway(unlogged_transcripts=2)
    naps: Final[list[float]] = []

    statuses: Final = _speech_run(gateway, media_probe.SpeechKit(tmp_path, _WAV), naps)

    fields: Final = gateway.heard[_TRANSCRIPTION_MODEL]
    assert (fields["file"], fields["language"]) == (_WAV, b"zh")
    assert gateway.transcripts == {f"call-{_TRANSCRIPTION_MODEL}": {"text": _HEARD}}
    assert naps == [media_probe.TRANSCRIPT_RETRY_SECONDS] * 3
    assert statuses[_TRANSCRIPTION_MODEL].endswith("transcript kept")


def test_a_transcript_the_gateway_never_logs_is_given_up_on_without_stopping_the_run(tmp_path: Path) -> None:
    gateway: Final = _Gateway(unlogged_transcripts=media_probe.TRANSCRIPT_ATTEMPTS)

    statuses: Final = _speech_run(gateway, media_probe.SpeechKit(tmp_path, _WAV), [])

    assert gateway.transcripts == {}
    assert statuses[_TRANSCRIPTION_MODEL].endswith("transcript not kept: the gateway never wrote the request down")
    assert statuses["IndexTTS-2"] == "spoke"


def test_without_the_recording_transcription_models_are_skipped_and_speech_models_still_read(tmp_path: Path) -> None:
    gateway: Final = _Gateway()

    statuses: Final = _speech_run(gateway, media_probe.SpeechKit(tmp_path, None), [])

    assert gateway.heard == {}
    assert statuses[_TRANSCRIPTION_MODEL] == "skipped: no recording to transcribe"
    assert statuses["IndexTTS-2"] == "spoke"


@pytest.mark.parametrize(
    ("path", "authorization", "status", "content"),
    (
        ("/audio/call-IndexTTS-2", "Bearer sk-master", 200, _WAV),
        ("/recording", "Bearer sk-master", 200, b"RIFF the recording"),
        ("/audio/call-IndexTTS-2", "Bearer sk-someone-else", 401, b""),
        ("/recording", "", 401, b""),
        ("/audio/call-missing", "Bearer sk-master", 404, b""),
        ("/audio/../secret", "Bearer sk-master", 404, b""),
        ("/audio/", "Bearer sk-master", 404, b""),
        ("/secret", "Bearer sk-master", 404, b""),
    ),
)
def test_the_probe_hands_kept_audio_only_to_the_gateway_and_only_from_its_audio_folder(
    tmp_path: Path, path: str, authorization: str, status: int, content: bytes
) -> None:
    audio_dir: Final = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "call-IndexTTS-2").write_bytes(_WAV)
    (tmp_path / "secret").write_bytes(b"not audio")
    kit: Final = media_probe.SpeechKit(audio_dir, b"RIFF the recording")

    assert media_probe.audio_file(path, authorization, "sk-master", kit) == (status, content)


@pytest.mark.parametrize(
    ("audio", "kind"),
    (
        (_WAV, "audio/wav"),
        (b"ID3\x04rest", "audio/mpeg"),
        (b"\xff\xfb\x90\x00", "audio/mpeg"),
        (b"OggS\x00", "audio/ogg"),
        (b'{"error": 1}', "application/octet-stream"),
        (b"", "application/octet-stream"),
    ),
)
def test_kept_audio_is_served_as_the_format_its_bytes_are_in(audio: bytes, kind: str) -> None:
    assert media_probe.audio_type(audio) == kind
