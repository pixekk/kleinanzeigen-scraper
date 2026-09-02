from __future__ import annotations

import logging
import random
import time
from typing import Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)


class FetchError(RuntimeError):
    pass


class BlockedError(FetchError):
    pass


class Fetcher:
    def __init__(self, user_agent: str, delay_seconds: float = 3.0, timeout_seconds: float = 30.0) -> None:
        self.delay_seconds = delay_seconds
        self._last_request = 0.0
        self._client = httpx.Client(
            http2=True,
            follow_redirects=True,
            timeout=timeout_seconds,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
                "Accept-Encoding": "gzip, deflate, br",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
                "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            },
        )

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        wait = self.delay_seconds + random.uniform(0, self.delay_seconds / 2) - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=5, min=5, max=60),
        reraise=True,
    )
    def _request(self, url: str, referer: Optional[str]) -> httpx.Response:
        self._throttle()
        headers = {"Referer": referer} if referer else {}
        response = self._client.get(url, headers=headers)
        if response.status_code in (403, 429, 503):
            raise BlockedError(f"blocked with HTTP {response.status_code} on {url}")
        response.raise_for_status()
        return response

    def get_html(self, url: str, referer: Optional[str] = None) -> str:
        log.debug("GET %s", url)
        try:
            return self._request(url, referer).text
        except BlockedError:
            raise
        except httpx.HTTPStatusError as exc:
            raise FetchError(f"HTTP {exc.response.status_code} on {url}") from exc
        except httpx.HTTPError as exc:
            raise FetchError(f"request failed for {url}: {exc}") from exc

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
