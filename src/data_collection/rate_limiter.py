"""Token-bucket rate limiter for polite web scraping.

Ensures we stay within per-domain request limits to avoid
overwhelming servers and triggering anti-crawl defenses.
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for a single domain's rate limit."""
    min_delay_ms: int = 100      # Minimum delay between requests
    max_delay_ms: int = 2000     # Maximum backoff delay
    backoff_base: float = 2.0    # Exponential backoff multiplier
    max_retries: int = 3         # Max retries on rate limit


class RateLimiter:
    """Token-bucket-based rate limiter with exponential backoff.

    Tracks request timing per domain and enforces minimum delays.
    Supports adaptive backoff when rate-limited (429) responses are detected.

    Usage:
        limiter = RateLimiter()
        async with limiter.acquire("fanqienovel.com"):
            response = await client.get(url)
            if response.status_code == 429:
                limiter.report_rate_limited("fanqienovel.com")
    """

    def __init__(self):
        # Per-domain state
        self._last_request: dict[str, float] = defaultdict(float)
        self._consecutive_429s: dict[str, int] = defaultdict(int)
        self._current_delays: dict[str, float] = {}  # domain -> current delay in seconds
        self._configs: dict[str, RateLimitConfig] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def configure(self, domain: str, config: RateLimitConfig) -> None:
        """Set rate limit configuration for a domain."""
        self._configs[domain] = config
        self._current_delays[domain] = config.min_delay_ms / 1000.0
        logger.debug("Rate limit configured for %s: %d-%dms",
                      domain, config.min_delay_ms, config.max_delay_ms)

    def acquire(self, domain: str):
        """Async context manager that waits until a request can be made."""

        class _AcquireContext:
            def __init__(self, parent, domain):
                self.parent = parent
                self.domain = domain

            async def __aenter__(self):
                await self.parent._wait_if_needed(self.domain)

            async def __aexit__(self, *args):
                self.parent._last_request[self.domain] = time.monotonic()

        return _AcquireContext(self, domain)

    async def _wait_if_needed(self, domain: str) -> None:
        """Wait if the minimum delay since last request hasn't elapsed."""
        async with self._locks[domain]:
            now = time.monotonic()
            last = self._last_request.get(domain, 0)
            current_delay = self._current_delays.get(
                domain,
                self._configs.get(domain, RateLimitConfig()).min_delay_ms / 1000.0,
            )
            elapsed = now - last

            if elapsed < current_delay:
                wait_time = current_delay - elapsed
                logger.debug("Rate limiting %s: waiting %.2fs", domain, wait_time)
                await asyncio.sleep(wait_time)

    def report_rate_limited(self, domain: str) -> None:
        """Call when a 429 response is received to increase backoff."""
        config = self._configs.get(domain, RateLimitConfig())
        self._consecutive_429s[domain] += 1
        backoff_count = self._consecutive_429s[domain]

        # Exponential backoff
        new_delay = min(
            config.min_delay_ms / 1000.0 * (config.backoff_base ** backoff_count),
            config.max_delay_ms / 1000.0,
        )
        self._current_delays[domain] = new_delay
        logger.warning("Rate limited on %s (x%d): backing off to %.2fs",
                       domain, backoff_count, new_delay)

    def report_success(self, domain: str) -> None:
        """Call on successful request to gradually reduce backoff."""
        if self._consecutive_429s[domain] > 0:
            self._consecutive_429s[domain] -= 1
            config = self._configs.get(domain, RateLimitConfig())
            self._current_delays[domain] = max(
                config.min_delay_ms / 1000.0,
                self._current_delays.get(domain, config.min_delay_ms / 1000.0) * 0.8,
            )

    def get_current_delay(self, domain: str) -> float:
        """Get the current enforced delay for a domain."""
        return self._current_delays.get(
            domain,
            self._configs.get(domain, RateLimitConfig()).min_delay_ms / 1000.0,
        )
