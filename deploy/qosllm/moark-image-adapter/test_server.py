import unittest
import urllib.request
import io
import json
from email.message import Message
from unittest.mock import patch

import server
from server import Handler, InvalidRequest, checked_image, request_bytes, upstream_request


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


class ImageAdapterTests(unittest.TestCase):
    def test_provider_error_redacts_configured_keys(self):
        with patch.object(server, "API_KEY", "upstream-secret"), patch.object(server, "ADAPTER_KEY", "adapter-secret"):
            self.assertEqual(server.safe_error_detail("bad upstream-secret and adapter-secret"),
                             "bad [REDACTED] and [REDACTED]")

    def test_shared_request_uses_configured_adapter_key(self):
        body = json.dumps({"model": "qwen-image-2.1-viggle-turbo", "prompt": "test"}).encode()
        headers = Message()
        headers["Authorization"] = "Bearer adapter-only-key"
        headers["Content-Length"] = str(len(body))
        handler = object.__new__(Handler)
        handler.path = "/v1/images/generations"
        handler.headers = headers
        handler.rfile = io.BytesIO(body)
        written = []
        handler._write = lambda status, data, extra=None: written.append((status, data))
        with patch.object(server, "ADAPTER_KEY", "adapter-only-key"), patch.object(
            server, "upstream_request", return_value=(PNG, {"task_id": "task", "latency_s": 1.0})
        ) as upstream:
            handler.do_POST()
        self.assertEqual(written[0][0], 200)
        upstream.assert_called_once_with({"model": "qwen-image-2.1-viggle-turbo", "prompt": "test"})

    def test_non_shared_key_is_rejected_before_upstream(self):
        headers = Message()
        headers["Authorization"] = "Bearer alice-personal-key"
        handler = object.__new__(Handler)
        handler.path = "/v1/images/generations"
        handler.headers = headers
        written = []
        handler._write = lambda status, data, extra=None: written.append(status)
        with patch.object(server, "ADAPTER_KEY", "adapter-only-key"), patch.object(server, "upstream_request", side_effect=AssertionError("must not call upstream")):
            handler.do_POST()
        self.assertEqual(written, [401])

    def test_success_polls_existing_task_and_downloads_once(self):
        calls = []
        statuses = iter([
            {"status": "waiting"},
            {"status": "success", "output": {"file_url": "https://storage.example/image.png"},
             "created_at": 1000, "started_at": 1800, "completed_at": 9800, "price": 0.2},
        ])
        times = iter([0.0, 1.0, 9.0])

        def submit(method, url, body):
            calls.append((method, url, body))
            if method == "POST":
                return {"task_id": "task-one", "urls": {"get": "https://ai.gitee.com/v1/task/task-one"}}
            return next(statuses)

        def download(url):
            calls.append(("DOWNLOAD", url, None))
            return PNG

        image, meta = upstream_request(
            {"model": "qwen-image-2.1-viggle-turbo", "prompt": "test", "size": "1024x1024", "seed": 42},
            submit=submit, download=download, clock=lambda: next(times), pause=lambda _: None,
        )

        self.assertIs(image, PNG)
        self.assertEqual(meta["task_id"], "task-one")
        self.assertEqual(meta["latency_s"], 9.0)
        self.assertEqual([call[0] for call in calls], ["POST", "GET", "GET", "DOWNLOAD"])
        self.assertEqual(calls[0][2]["width"], 1024)
        self.assertEqual(calls[0][2]["height"], 1024)
        self.assertEqual(calls[0][2]["seed"], 42)

    def test_rejects_multiple_images_before_paid_submission(self):
        def submit(method, url, body):
            self.fail("invalid request must not submit a paid task")

        with self.assertRaisesRegex(InvalidRequest, "only one image"):
            upstream_request({"prompt": "test", "n": 2}, submit=submit)

    def test_rejects_unsupported_size_before_paid_submission(self):
        def submit(method, url, body):
            self.fail("invalid request must not submit a paid task")

        with self.assertRaisesRegex(InvalidRequest, "1024x1024"):
            upstream_request({"prompt": "test", "size": "2048x2048"}, submit=submit)

    def test_negative_prompt_reaches_upstream(self):
        submitted = []

        def submit(method, url, body):
            if method == "POST":
                submitted.append(body)
                return {"task_id": "task-one", "urls": {"get": "https://ai.gitee.com/v1/task/task-one"}}
            return {"status": "success", "output": {"file_url": "https://storage.example/image.png"}}

        upstream_request({"prompt": "ramen", "negative_prompt": "chopsticks", "seed": 42},
                         submit=submit, download=lambda _: PNG)
        self.assertEqual(submitted[0]["negative_prompt"], "chopsticks")
        self.assertEqual(submitted[0]["seed"], 42)

    def test_failed_task_does_not_download_or_submit_again(self):
        methods = []

        def submit(method, url, body):
            methods.append(method)
            if method == "POST":
                return {"task_id": "task-one", "urls": {"get": "https://ai.gitee.com/v1/task/task-one"}}
            return {"status": "failure"}

        def download(url):
            self.fail("failed task must not download")

        with self.assertRaisesRegex(RuntimeError, "failure"):
            upstream_request({"prompt": "test"}, submit=submit, download=download)
        self.assertEqual(methods, ["POST", "GET"])

    def test_rejects_json_error_blob_as_image(self):
        with self.assertRaisesRegex(ValueError, "non-image"):
            checked_image(b'{"code":"MissingDateHeader"}')

    def test_download_does_not_send_api_key(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return PNG

        requests = []

        def open_url(request, timeout):
            requests.append(request)
            return Response()

        with patch.object(urllib.request, "urlopen", open_url):
            self.assertEqual(request_bytes("https://storage.example/image.png"), PNG)
        self.assertNotIn("Authorization", requests[0].headers)


if __name__ == "__main__":
    unittest.main()
