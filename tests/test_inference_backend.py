"""Panoptes' thin inference interface against the Interception HTTP contract."""

import asyncio
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from panoptes.inference import InterceptionBackend, InferenceError, inference_key


class Fixture(BaseHTTPRequestHandler):
    requests = []
    completed = False

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.__class__.requests.append((self.path, self.headers.get("Authorization"), body))
        self.reply(202, {"request_id": "abc123", "state": "WAITING_FOR_INFERENCE",
                         "status_url": "/bridge/requests/abc123"})

    def do_GET(self):
        self.__class__.requests.append((self.path, self.headers.get("Authorization"), None))
        self.reply(200, {"request_id": "abc123",
                         "state": "COMPLETED" if self.__class__.completed else "WAITING_FOR_INFERENCE",
                         "response": {"role": "assistant", "content": "ok"} if self.__class__.completed else None,
                         "checkpoint": {"run_id": "r", "node": "evaluate"}})

    def reply(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class BackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        Fixture.requests = []
        Fixture.completed = False

    def test_submit_status_result_with_exact_checkpoint(self):
        async def run():
            backend = InterceptionBackend(self.url, "test-token")
            checkpoint = {"run_id": "r", "node": "evaluate"}
            request_id = await backend.submit(
                {"model": "manual", "messages": [{"role": "user", "content": "Evaluate"}]},
                key=inference_key("r", "critic", "evaluate", "0"),
                metadata={"caller": {"agent": "critic"}}, checkpoint=checkpoint)
            self.assertEqual(request_id, "abc123")
            self.assertEqual((await backend.status(request_id))["state"], "WAITING_FOR_INFERENCE")
            self.assertIsNone(await backend.result(request_id, checkpoint=checkpoint))
            Fixture.completed = True
            self.assertEqual((await backend.result(request_id, checkpoint=checkpoint))["content"], "ok")
        asyncio.run(run())
        path, auth, body = Fixture.requests[0]
        self.assertEqual((path, auth), ("/bridge/requests", "Bearer test-token"))
        self.assertEqual(body["key"], "panoptes:r:critic:evaluate:0")
        self.assertEqual(body["checkpoint"], {"run_id": "r", "node": "evaluate"})

    def test_connection_file_and_rejected_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "connection.json"
            path.write_text(json.dumps({"base_url": self.url + "/v1", "api_key": "test-token"}))
            self.assertEqual(InterceptionBackend.from_connection(path).base_url, self.url)
        with self.assertRaises(ValueError):
            InterceptionBackend("http://example.org:8742", "secret")
        with self.assertRaises(ValueError):
            InterceptionBackend(self.url + "/v1", "secret")

    def test_mismatched_checkpoint_does_not_return_result(self):
        Fixture.completed = True
        async def run():
            with self.assertRaises(InferenceError):
                await InterceptionBackend(self.url, "test-token").result(
                    "abc123", checkpoint={"run_id": "wrong", "node": "evaluate"})
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
