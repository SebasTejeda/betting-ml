"""Test client for functional API tests once every read needs credentials (spec 003, T007).

Reads (GET, and POST /api/v1/predictions, which computes without changing state) carry the
machine key unless the test sets X-API-Key itself. Writes are never authenticated
implicitly: a write without headers stays anonymous, so "missing key → 401" tests keep their
meaning. Authentication itself is tested in test_route_access.py and test_api_auth.py.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

READ_POSTS = {"/api/v1/predictions"}


class ReaderClient(TestClient):
    def __init__(self, app: Any, key: str, **kwargs: Any) -> None:
        super().__init__(app, **kwargs)
        self.machine_key = key

    def request(self, method: str, url: Any, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        is_read = method.upper() == "GET" or (
            method.upper() == "POST" and str(url).split("?")[0] in READ_POSTS
        )
        headers = dict(kwargs.pop("headers", None) or {})
        if is_read and not any(k.lower() == "x-api-key" for k in headers):
            headers["X-API-Key"] = self.machine_key
        return super().request(method, url, *args, headers=headers or None, **kwargs)
