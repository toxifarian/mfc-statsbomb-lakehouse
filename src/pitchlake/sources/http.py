"""Resilient HTTP client shared by all API sources.

Design notes (things the vendor SDK does not do for us):
* statsbombpy returns ``[]`` on any non-200 response — a 401 or 503 looks
  exactly like "no data". Here every non-retryable failure *raises*.
* 429 / 5xx / connection errors are retried with exponential backoff + jitter,
  honouring ``Retry-After``.
* A token-bucket rate limiter is shared across worker threads so parallel
  match downloads stay inside the vendor's limits.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class SourceHTTPError(RuntimeError):
    def __init__(self, url: str, status: int | None, message: str):
        super().__init__(f"{status} {message} <- {url}")
        self.url, self.status = url, status


class NotFound(SourceHTTPError):
    """404 – resource legitimately absent (e.g. no 360 data for a match)."""


@dataclass
class HttpResponse:
    url: str
    status: int
    content: bytes
    elapsed_s: float
    attempts: int


class RateLimiter:
    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second if per_second else 0
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        if not self.interval:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next - now
            self._next = max(now, self._next) + self.interval
        if sleep_for > 0:
            time.sleep(sleep_for)


class HttpClient:
    def __init__(
        self,
        timeout_s: float = 60,
        max_retries: int = 5,
        backoff_base_s: float = 1.0,
        requests_per_second: float = 8,
        pool_size: int = 16,
        auth: tuple[str, str] | None = None,
        user_agent: str = "pitchlake/1.0 (+data-engineering)",
    ):
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.limiter = RateLimiter(requests_per_second)
        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers["User-Agent"] = user_agent
        if auth:
            self.session.auth = auth

    def _sleep_for(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return self.backoff_base_s * (2 ** (attempt - 1)) + random.uniform(0, self.backoff_base_s)

    def get(self, url: str) -> HttpResponse:
        attempt = 0
        while True:
            attempt += 1
            self.limiter.wait()
            start = time.monotonic()
            try:
                resp = self.session.get(url, timeout=self.timeout_s)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt > self.max_retries:
                    raise SourceHTTPError(
                        url, None, f"network failure after {attempt} attempts: {exc}"
                    ) from exc
                delay = self._sleep_for(attempt, None)
                log.warning("network error on %s (attempt %s) – retrying in %.1fs", url, attempt, delay)
                time.sleep(delay)
                continue

            if resp.status_code == 200:
                return HttpResponse(url, 200, resp.content, time.monotonic() - start, attempt)
            if resp.status_code == 404:
                raise NotFound(url, 404, "not found")
            if resp.status_code in (401, 403):
                raise SourceHTTPError(
                    url, resp.status_code, "authentication/authorisation failed – check credentials"
                )
            if resp.status_code in RETRYABLE_STATUS and attempt <= self.max_retries:
                delay = self._sleep_for(attempt, resp.headers.get("Retry-After"))
                log.warning(
                    "HTTP %s on %s (attempt %s) – retrying in %.1fs", resp.status_code, url, attempt, delay
                )
                time.sleep(delay)
                continue
            raise SourceHTTPError(url, resp.status_code, resp.text[:200])
