"""Retry decorators for resilient operations."""

import asyncio
import functools
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def async_retry(
    max_attempts: int = 3,
    base_delay: float = 2.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,),
):
    """Decorator for async functions with exponential backoff retry.

    Args:
        max_attempts: Maximum number of attempts (including first call).
        base_delay: Initial delay between retries in seconds.
        backoff_factor: Multiplier for successive delays.
        exceptions: Tuple of exception types to catch and retry.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_error = e
                    if attempt < max_attempts:
                        delay = base_delay * (backoff_factor ** (attempt - 1))
                        logger.warning(
                            "%s.%s attempt %d/%d failed: %s. Retrying in %.1fs...",
                            func.__module__, func.__name__,
                            attempt, max_attempts, e, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "%s.%s failed after %d attempts: %s",
                            func.__module__, func.__name__,
                            max_attempts, e,
                        )
            raise last_error  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator


def sync_retry(
    max_attempts: int = 3,
    base_delay: float = 2.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,),
):
    """Decorator for sync functions with exponential backoff retry."""
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_error = e
                    if attempt < max_attempts:
                        delay = base_delay * (backoff_factor ** (attempt - 1))
                        logger.warning(
                            "%s.%s attempt %d/%d failed: %s. Retrying in %.1fs...",
                            func.__module__, func.__name__,
                            attempt, max_attempts, e, delay,
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "%s.%s failed after %d attempts: %s",
                            func.__module__, func.__name__,
                            max_attempts, e,
                        )
            raise last_error  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator
