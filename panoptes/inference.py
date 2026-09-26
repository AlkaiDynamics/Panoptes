"""Thin native inference seam. Interception owns every durable request lifecycle."""

import asyncio
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit


class InferenceError(RuntimeError):
    """Safe error at the external inference boundary."""


def inference_key(run, agent, step, iteration):
    """Stable identity for one logical inference step across retries."""
    parts = [str(part) for part in (run, agent, step, iteration)]
    if any(not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", part) or not part.strip(".") for part in parts):
        raise ValueError("inference key parts must be nonempty safe ID segments")
    return "panoptes:" + ":".join(parts)


class InferenceBackend(Protocol):
    async def submit(self, request, *, key, metadata, checkpoint) -> str: ...
    async def status(self, request_id) -> dict: ...
    async def result(self, request_id, *, checkpoint) -> dict | None: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


class InterceptionBackend:
    """Nonblocking caller interface for Interception's local durable HTTP API.

    The caller stores the returned ID in its existing workflow checkpoint and
    polls later. No mailbox, request ledger, or resume state is created here.
    """

    def __init__(self, base_url, token, *, timeout=10):
        parsed = urlsplit(base_url)
        if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or not parsed.port):
            raise ValueError("Interception requires a loopback HTTP origin")
        if not isinstance(token, str) or not token:
            raise ValueError("Interception token is required")
        if timeout <= 0:
            raise ValueError("HTTP timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    @classmethod
    def from_connection(cls, path):
        """Use Interception's generated .inference_bridge/connection.json."""
        with Path(path).open(encoding="utf-8") as file:
            config = json.load(file)
        parsed = urlsplit(config["base_url"])
        if parsed.path.rstrip("/") != "/v1" or parsed.query or parsed.fragment:
            raise ValueError("connection base_url must end in /v1")
        return cls(f"{parsed.scheme}://{parsed.netloc}", config["api_key"])

    def _call(self, method, path, payload=None):
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as error:
            raise InferenceError(f"Interception HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise InferenceError("Interception bridge unavailable") from None
        if len(raw) > 8 * 1024 * 1024:
            raise InferenceError("Interception response exceeds size limit")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise InferenceError("Interception returned invalid JSON") from None
        if not isinstance(result, dict):
            raise InferenceError("Interception returned invalid JSON object")
        return result

    async def submit(self, request, *, key, metadata=None, checkpoint=None):
        if not isinstance(key, str) or not key or len(key) > 512:
            raise ValueError("stable idempotency key is required")
        reply = await asyncio.to_thread(self._call, "POST", "/bridge/requests",
                                        {"request": request, "key": key,
                                         "metadata": metadata, "checkpoint": checkpoint})
        request_id = reply.get("request_id")
        if (not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id)
                or reply.get("state") not in {"WAITING_FOR_INFERENCE", "COMPLETED"}):
            raise InferenceError("Interception returned invalid submission receipt")
        return request_id

    async def status(self, request_id):
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id):
            raise ValueError("invalid Interception request ID")
        reply = await asyncio.to_thread(self._call, "GET", f"/bridge/requests/{request_id}")
        if reply.get("request_id") != request_id or reply.get("state") not in {"WAITING_FOR_INFERENCE", "COMPLETED"}:
            raise InferenceError("Interception returned mismatched request state")
        return reply

    async def result(self, request_id, *, checkpoint):
        reply = await self.status(request_id)
        if reply.get("checkpoint") != checkpoint:
            raise InferenceError("Interception checkpoint does not match waiting node")
        if reply["state"] == "WAITING_FOR_INFERENCE":
            return None
        response = reply.get("response")
        if not isinstance(response, dict) or response.get("role") != "assistant":
            raise InferenceError("Interception returned invalid assistant response")
        return response
