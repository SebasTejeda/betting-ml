"""Small HTTP helper with retries, backoff and a polite delay between requests."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "betting-ml/0.1 (research project; contact: repo owner)"


class DownloadError(RuntimeError):
    pass


class HttpClient:
    def __init__(
        self,
        delay_seconds: float = 0.0,
        retries: int = 3,
        backoff_seconds: float = 5.0,
        timeout: float = 30.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.delay_seconds = delay_seconds
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self._sleep = sleep
        self._last_request: float | None = None

    def _respect_delay(self) -> None:
        if self._last_request is None or self.delay_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay_seconds:
            self._sleep(self.delay_seconds - elapsed)

    def get(self, url: str, **kwargs: object) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._respect_delay()
            try:
                response = self.session.get(url, timeout=self.timeout, **kwargs)  # type: ignore[arg-type]
                self._last_request = time.monotonic()
                if response.status_code == 404:
                    raise DownloadError(f"404 Not Found: {url}")
                response.raise_for_status()
                return response
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
