import logging
import random
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import httpx

log = logging.getLogger(__name__)


class SourceError(RuntimeError):
    pass


class PublicClient:
    def __init__(self, interval=0.6, transport=None, sleep=time.sleep):
        self.client = httpx.Client(timeout=30, transport=transport, headers={
            "User-Agent": "RobloxTrendMonitor/0.1 (local market research; public read-only APIs)",
            "Accept": "application/json",
        })
        self.interval, self.sleep, self.last = interval, sleep, 0.0
        self.failed_requests = 0

    def get(self, url, params=None):
        for attempt in range(4):
            self.sleep(max(0, self.interval - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            response = None
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object")
                return payload
            except (httpx.HTTPError, ValueError) as exc:
                self.failed_requests += 1
                log.warning("Request failed attempt=%s url=%s error=%s", attempt + 1, url, exc)
                retryable = response is None or response.status_code == 429 or response.status_code >= 500
                if not retryable or attempt == 3:
                    raise SourceError(f"{url}: {exc}") from exc
                delay = 2 ** attempt + random.uniform(0, 0.3)
                if response is not None and response.headers.get("Retry-After"):
                    value = response.headers["Retry-After"]
                    try:
                        delay = max(delay, float(value))
                    except ValueError:
                        try:
                            delay = max(delay, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
                        except (ValueError, TypeError):
                            log.warning("Invalid Retry-After header: %s", value)
                # Do not retry early if a server asks for a long pause; defer to the next cycle.
                if delay > 120:
                    raise SourceError(f"{url}: server requested {delay:.0f}s cooldown; deferred") from exc
                self.sleep(delay)

    def close(self):
        self.client.close()
