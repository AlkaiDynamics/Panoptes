"""Small JSON/HTTP client for the pinned ncz-os/mnemos v1 API.

The upstream service currently requires Python 3.13 and a sizeable runtime.
Panoptes keeps its Python 3.11 baseline by treating Mnemos as an external
service and implementing only the documented, synchronous REST boundary.
"""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class MnemosError(RuntimeError):
    """A safe, user-facing Mnemos transport or protocol failure."""


class _RejectRedirects(HTTPRedirectHandler):
    """Do not risk forwarding a bearer token to a redirected host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class MnemosClient:
    """Call Mnemos memory search and creation endpoints.

    ``base_url`` is an administrator-supplied service boundary, never a URL
    discovered from model output. Redirects are rejected so credentials stay
    bound to that configured origin.
    """

    def __init__(self, base_url, api_key=None, timeout=5.0, opener=None):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Mnemos base URL must be an absolute http(s) URL without credentials, query, or fragment")
        if parsed.path not in {"", "/"}:
            raise ValueError("Mnemos base URL must not include a path")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.api_key = api_key
        self.timeout = timeout
        self.opener = opener or build_opener(_RejectRedirects())

    def _request(self, method, path, payload):
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read(2_000_001)
                if len(body) > 2_000_000:
                    raise MnemosError("Mnemos response exceeds 2 MB")
        except HTTPError as error:
            raise MnemosError(f"Mnemos returned HTTP {error.code}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise MnemosError("Mnemos request failed") from error
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MnemosError("Mnemos returned invalid JSON") from error
        if not isinstance(result, (dict, list)):
            raise MnemosError("Mnemos returned an unexpected JSON value")
        return result

    def search(self, query, *, category=None, limit=10, semantic=False):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be nonempty")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer from 1 through 500")
        payload = {"query": query, "limit": limit, "semantic": bool(semantic)}
        if category:
            payload["category"] = category
        return self._request("POST", "/v1/memories/search", payload)

    def create(self, content, *, category="projects", subcategory=None, metadata=None):
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content must be nonempty")
        if not isinstance(category, str) or not category.strip():
            raise ValueError("category must be nonempty")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        payload = {"content": content, "category": category}
        if subcategory:
            payload["subcategory"] = subcategory
        if metadata is not None:
            payload["metadata"] = metadata
        return self._request("POST", "/v1/memories", payload)
