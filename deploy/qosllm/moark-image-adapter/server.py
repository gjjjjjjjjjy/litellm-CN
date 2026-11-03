import base64
import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Final


UPSTREAM_BASE: Final[str] = os.environ.get("MOARK_IMAGE_BASE", "https://ai.gitee.com")
UPSTREAM_MODEL: Final[str] = os.environ.get("MOARK_IMAGE_MODEL", "qwen-image-2.1-viggle-turbo")
API_KEY: Final[str] = os.environ.get("MOARK_API_KEY", "")
ADAPTER_KEY: Final[str] = os.environ.get("IMAGE_ADAPTER_KEY", "")
POLL_SECONDS: Final[float] = float(os.environ.get("MOARK_POLL_SECONDS", "2"))
TIMEOUT_SECONDS: Final[float] = float(os.environ.get("MOARK_TASK_TIMEOUT", "900"))


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class InvalidRequest(ValueError):
    pass


def safe_error_detail(value: str) -> str:
    for secret in (API_KEY, ADAPTER_KEY):
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value[:500]


class NoAuthorizedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("upstream redirected an authorized request")


def request_json(
    method: str, url: str, body: dict[str, object] | None = None, auth: bool = True,
) -> dict[str, object]:
    target = urllib.parse.urlsplit(url)
    upstream = urllib.parse.urlsplit(UPSTREAM_BASE)
    if target.scheme != "https" or target.netloc != upstream.netloc:
        raise ValueError("refusing to send the API key outside the upstream host")
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = f"Bearer {API_KEY}"
    data = None if body is None else json_bytes(body)
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(NoAuthorizedRedirect)
    with opener.open(request, timeout=300) as response:
        result = json.loads(response.read())
    if not isinstance(result, dict):
        raise ValueError("upstream returned a non-object JSON response")
    return result


def request_bytes(url: str) -> bytes:
    target = urllib.parse.urlsplit(url)
    if target.scheme != "https" or target.hostname in (None, "localhost", "127.0.0.1", "::1"):
        raise ValueError("refusing a non-HTTPS image URL")
    request = urllib.request.Request(url, method="GET")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return response.read()
        except urllib.error.HTTPError:
            raise
        except (http.client.IncompleteRead, urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 3:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("image download failed")


def checked_image(blob: bytes) -> bytes:
    if len(blob) >= 24 and blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return blob
    if len(blob) >= 4 and blob.startswith(b"\xff\xd8"):
        return blob
    if len(blob) >= 12 and blob.startswith(b"RIFF") and blob[8:12] == b"WEBP":
        return blob
    raise ValueError("upstream returned a non-image response")


def upstream_request(
    body: dict[str, object],
    submit: Callable[[str, str, dict[str, object] | None], dict[str, object]] = request_json,
    download: Callable[[str], bytes] = request_bytes,
    clock: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
) -> tuple[bytes, dict[str, object]]:
    if body.get("model") not in (None, UPSTREAM_MODEL):
        raise InvalidRequest("unsupported image model")
    if not isinstance(body.get("prompt"), str) or not body["prompt"].strip():
        raise InvalidRequest("prompt must be a non-empty string")
    if len(body["prompt"]) > 4000:
        raise InvalidRequest("prompt exceeds 4000 characters")
    if body.get("n", 1) != 1:
        raise InvalidRequest("only one image per request is supported")
    if "response_format" in body and body["response_format"] != "b64_json":
        raise InvalidRequest("only b64_json response format is supported")
    started = clock()
    if body.get("size", "1024x1024") != "1024x1024":
        raise InvalidRequest("only 1024x1024 images are supported")
    seed = body.get("seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2147483647):
        raise InvalidRequest("seed must be an integer between 0 and 2147483647")
    negative_prompt = body.get("negative_prompt")
    if negative_prompt is not None and (not isinstance(negative_prompt, str) or len(negative_prompt) > 1000):
        raise InvalidRequest("negative_prompt must be a string of at most 1000 characters")
    payload = {
        "model": UPSTREAM_MODEL, "prompt": body["prompt"], "return_image_format": "PNG",
        "width": 1024, "height": 1024,
        **({"seed": seed} if seed is not None else {}),
        **({"negative_prompt": negative_prompt} if negative_prompt else {}),
    }
    task = submit("POST", f"{UPSTREAM_BASE}/v1/async/images/generations", payload)
    urls = task.get("urls")
    if not isinstance(urls, dict) or not urls.get("get"):
        raise ValueError("upstream did not provide a task query URL")
    task_url = urllib.parse.urljoin(UPSTREAM_BASE, str(urls["get"]))
    task_id = str(task.get("task_id", ""))
    while True:
        current = submit("GET", task_url, None)
        status = str(current.get("status", ""))
        if status not in {"waiting", "in_progress", "running", "pending", "queued"}:
            break
        if clock() - started > TIMEOUT_SECONDS:
            raise TimeoutError(f"task {task_id} timed out")
        pause(POLL_SECONDS)
    if current.get("status") != "success":
        raise RuntimeError(f"upstream task {task_id} ended with status {current.get('status')}")
    output = current.get("output")
    if not isinstance(output, dict) or not output.get("file_url"):
        raise RuntimeError("upstream task succeeded without an output file")
    image = checked_image(download(str(output["file_url"])))
    timestamps = {
        "created_at": current.get("created_at"),
        "started_at": current.get("started_at"),
        "completed_at": current.get("completed_at"),
    }
    created_at = timestamps["created_at"]
    started_at = timestamps["started_at"]
    completed_at = timestamps["completed_at"]
    queue_s = (
        (started_at - created_at) / 1000
        if all(isinstance(value, (int, float)) for value in (created_at, started_at)) else None
    )
    run_s = (
        (completed_at - started_at) / 1000
        if all(isinstance(value, (int, float)) for value in (started_at, completed_at)) else None
    )
    return image, {"task_id": task_id, "price": current.get("price"), **timestamps,
                   "queue_s": queue_s, "run_s": run_s, "latency_s": clock() - started}


class Handler(BaseHTTPRequestHandler):
    server_version = "MoarkImageAdapter/1.0"

    def _write(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._write(HTTPStatus.OK, b'{"status":"ok"}')
            return
        self._write(HTTPStatus.NOT_FOUND, json_bytes({"error": {"message": "not found"}}))

    def do_POST(self) -> None:
        if self.path != "/v1/images/generations":
            self._write(HTTPStatus.NOT_FOUND, json_bytes({"error": {"message": "not found"}}))
            return
        authorization = self.headers.get("Authorization", "")
        if not ADAPTER_KEY or authorization != f"Bearer {ADAPTER_KEY}":
            self._write(HTTPStatus.UNAUTHORIZED, json_bytes({"error": {"message": "invalid adapter key"}}))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 65536:
                raise InvalidRequest("request body must be between 1 and 65536 bytes")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise InvalidRequest("request body must be a JSON object")
            image, meta = upstream_request(body)
            headers = {
                "X-Image-Task-Id": str(meta["task_id"]),
                "X-Image-Latency-S": f"{meta['latency_s']:.3f}",
            }
            if meta.get("queue_s") is not None:
                headers["X-Image-Queue-S"] = f"{meta['queue_s']:.3f}"
            if meta.get("run_s") is not None:
                headers["X-Image-Run-S"] = f"{meta['run_s']:.3f}"
            if meta.get("price") is not None:
                headers["X-Image-Cost-CNY"] = str(meta["price"])
            self._write(
                HTTPStatus.OK,
                json_bytes({
                    "created": int(time.time()),
                    "data": [{"b64_json": base64.b64encode(image).decode("ascii")}],
                }),
                headers,
            )
        except (InvalidRequest, json.JSONDecodeError) as error:
            self._write(
                HTTPStatus.BAD_REQUEST,
                json_bytes({"error": {"message": str(error), "type": "invalid_request_error"}}),
            )
        except urllib.error.HTTPError as error:
            detail = safe_error_detail(error.read(4096).decode("utf-8", "replace"))
            self._write(error.code, json_bytes({"error": {"message": detail, "type": "upstream_error"}}))
        except Exception as error:
            self._write(
                HTTPStatus.BAD_GATEWAY,
                json_bytes({"error": {"message": safe_error_detail(str(error)), "type": "image_generation_error"}}),
            )


if __name__ == "__main__":
    if not API_KEY or not ADAPTER_KEY or API_KEY == ADAPTER_KEY:
        raise SystemExit("MOARK_API_KEY and IMAGE_ADAPTER_KEY must be set to different non-empty values")
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
