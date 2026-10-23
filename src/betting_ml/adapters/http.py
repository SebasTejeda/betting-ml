"""Small HTTP helper with retries, backoff and a polite delay between requests.

Every download is bounded (spec 004, integration I07; deferred from the spec 003 audit, T021):
``timeout`` per network operation, ``deadline_seconds`` for the whole body and ``max_bytes``
for its size, so a slow or oversized answer of an external source can neither hang a refresh
nor fill the memory or the disk. Going over a bound is not retried."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "betting-ml/0.1 (research project; contact: repo owner)"
# The largest file downloaded today is an Understat season (~0.6 MB): a wide margin.
DEFAULT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_DEADLINE_SECONDS = 120.0
CHUNK_BYTES = 64 * 1024


class DownloadError(RuntimeError):
    pass


class DownloadTooLargeError(DownloadError):
    pass


@dataclass(frozen=True)
class Download:
    url: str
    content: bytes


class HttpClient:
    def __init__(
        self,
        delay_seconds: float = 0.0,
        retries: int = 3,
        backoff_seconds: float = 5.0,
        timeout: float = 30.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_bytes: int = DEFAULT_MAX_BYTES,
        deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.delay_seconds = delay_seconds
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self._sleep = sleep
        self._last_request: float | None = None
        self.max_bytes = max_bytes
        self.deadline_seconds = deadline_seconds
        self._clock = clock

    def _respect_delay(self) -> None:
        if self._last_request is None or self.delay_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay_seconds:
            self._sleep(self.delay_seconds - elapsed)

    def get(self, url: str, **kwargs: object) -> Download:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._respect_delay()
            try:
                response = self.session.get(url, timeout=self.timeout, stream=True, **kwargs)  # type: ignore[arg-type]
                try:
                    self._last_request = time.monotonic()
                    if response.status_code == 404:
                        raise DownloadError(f"404 Not Found: {url}")
                    response.raise_for_status()
                    return Download(url, self._body(url, response))
                finally:
                    response.close()
            except DownloadError:
                raise
            except requests.RequestException as exc:
                self._last_request = time.monotonic()
                last_error = exc
                wait = self.backoff_seconds * attempt
                logger.warning("GET %s failed (%s), retry %d in %.0fs", url, exc, attempt, wait)
                if attempt < self.retries:
                    self._sleep(wait)
        raise DownloadError(f"GET {url} failed after {self.retries} attempts: {last_error}")

    def _body(self, url: str, response: requests.Response) -> bytes:
        """The body, read in chunks: refused as soon as it is too large or too slow."""
        declared = response.headers.get("Content-Length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            raise DownloadTooLargeError(
                f"GET {url}: {declared} bytes declared, limit {self.max_bytes}"
            )
        started = self._clock()
        body = bytearray()
        for chunk in response.iter_content(CHUNK_BYTES):
            body += chunk
            if len(body) > self.max_bytes:
                raise DownloadTooLargeError(f"GET {url}: more than {self.max_bytes} bytes")
            if self._clock() - started > self.deadline_seconds:
                raise DownloadError(f"GET {url}: body not complete after {self.deadline_seconds}s")
        return bytes(body)
