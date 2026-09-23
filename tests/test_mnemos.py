import contextlib
import io
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from panoptes.cli import main
from panoptes.integrations.mnemos import MnemosClient, MnemosError


class _MnemosFixture(BaseHTTPRequestHandler):
    requests = []
    response_status = 200

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        self.__class__.requests.append({
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "body": body,
        })
        self.send_response(self.__class__.response_status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if self.__class__.response_status < 400:
            if self.path.endswith("/search"):
                self.wfile.write(json.dumps({"count": 1, "memories": [{"content": "saved"}]}).encode())
            else:
                self.wfile.write(json.dumps({"id": "mem-1", **body}).encode())
        else:
            self.wfile.write(b'{"detail":"denied"}')

    def log_message(self, format, *args):
        return


class MnemosIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _MnemosFixture)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        _MnemosFixture.requests = []
        _MnemosFixture.response_status = 200

    def test_search_uses_pinned_v1_contract_and_bearer_auth(self):
        result = MnemosClient(self.base_url, api_key="secret").search(
            "latest checkpoint", category="projects", limit=4, semantic=True)
        self.assertEqual(result["count"], 1)
        self.assertEqual(_MnemosFixture.requests, [{
            "path": "/v1/memories/search",
            "authorization": "Bearer secret",
            "body": {"query": "latest checkpoint", "limit": 4,
                     "semantic": True, "category": "projects"},
        }])

    def test_cli_stores_memory_without_putting_key_on_command_line(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"PANOPTES_TEST_MNEMOS_KEY": "secret"}), contextlib.redirect_stdout(output):
            main(["memory-store", "checkpoint 12", "--base-url", self.base_url,
                  "--api-key-env", "PANOPTES_TEST_MNEMOS_KEY",
                  "--subcategory", "checkpoints",
                  "--metadata-json", '{"source":"panoptes"}'])
        self.assertEqual(json.loads(output.getvalue())["id"], "mem-1")
        self.assertEqual(_MnemosFixture.requests[0], {
            "path": "/v1/memories",
            "authorization": "Bearer secret",
            "body": {"content": "checkpoint 12", "category": "projects",
                     "subcategory": "checkpoints", "metadata": {"source": "panoptes"}},
        })

    def test_http_error_is_safe_and_does_not_echo_key_or_body(self):
        _MnemosFixture.response_status = 401
        with self.assertRaisesRegex(MnemosError, "HTTP 401") as raised:
            MnemosClient(self.base_url, api_key="do-not-leak").search("checkpoint")
        self.assertNotIn("do-not-leak", str(raised.exception))
        self.assertNotIn("denied", str(raised.exception))

    def test_rejects_ambiguous_or_credentialed_base_urls(self):
        for value in ("file:///tmp/mnemos", "https://user:pass@example.test",
                      "https://example.test/api", "https://example.test?q=1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MnemosClient(value)


if __name__ == "__main__":
    unittest.main()
