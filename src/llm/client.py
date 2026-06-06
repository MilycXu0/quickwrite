"""Anthropic SDK wrapper for the novel writer agent.

Provides a clean interface for calling Claude models with built-in
cost tracking, retry logic, and streaming support.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import anthropic
from anthropic.types import Message, MessageStreamEvent

from src.llm.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Normalized response from any LLM call."""
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    latency_ms: int
    stop_reason: str


class LLMClient:
    """Wrapper around the Anthropic SDK with cost tracking and retry logic."""

    # Pricing per 1M tokens (as of 2025)
    PRICING = {
        "claude-opus-4-8-20251101":       {"input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_write": 30.00},
        "claude-sonnet-4-6-20250514":     {"input": 3.00,  "output": 15.00, "cache_read": 0.30, "cache_write": 6.00},
        "claude-haiku-4-5-20251001":      {"input": 0.80,  "output": 4.00,  "cache_read": 0.08, "cache_write": 1.60},
    }

    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 2.0  # seconds

    def __init__(self, api_key: Optional[str] = None, cost_tracker: Optional[CostTracker] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY must be set or provided")
        self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        self.cost_tracker = cost_tracker or CostTracker()

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "claude-sonnet-4-6-20250514",
        max_tokens: int = 4096,
        temperature: float = 0.8,
        enable_thinking: bool = True,
        thinking_budget: int = 1024,
        enable_caching: bool = True,
        stream: bool = False,
        extra_headers: Optional[dict] = None,
    ) -> LLMResponse:
        """Generate a response from Claude.

        Args:
            system_prompt: The system prompt (cached if enable_caching=True).
            user_message: The user message (varies per call).
            model: Model ID string.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature (0.0-1.0).
            enable_thinking: Whether to use extended thinking.
            thinking_budget: Token budget for thinking (if enabled).
            enable_caching: Whether to use prompt caching on system prompt.
            stream: Whether to stream the response.
            extra_headers: Additional HTTP headers.

        Returns:
            LLMResponse with text, token counts, cost, and latency.
        """
        # Build system message with optional cache control
        system_content = system_prompt
        if enable_caching:
            # Append cache_control to the last content block
            system_content = [{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }]

        # Build thinking config
        thinking = None
        if enable_thinking:
            thinking = {"type": "enabled", "budget_tokens": thinking_budget}

        logger.info("Calling %s (max_tokens=%d, thinking=%s, cached=%s)",
                     model, max_tokens, enable_thinking, enable_caching)

        start_time = time.monotonic()
        last_error = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                if stream:
                    response = await self._stream_call(
                        model=model,
                        system=system_content,
                        messages=[{"role": "user", "content": user_message}],
                        max_tokens=max_tokens,
                        temperature=temperature,
                        thinking=thinking,
                        extra_headers=extra_headers,
                    )
                else:
                    response = await self._client.messages.create(
                        model=model,
                        max_tokens=max_tokens,
                        system=system_content,
                        messages=[{"role": "user", "content": user_message}],
                        temperature=temperature,
                        thinking=thinking,
                        extra_headers=extra_headers,
                    )

                latency_ms = int((time.monotonic() - start_time) * 1000)
                result = self._parse_response(response, model, latency_ms)

                # Track cost
                if self.cost_tracker:
                    self.cost_tracker.record(
                        stage="generation",
                        model=model,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        cache_read_tokens=result.cache_read_tokens,
                        cache_write_tokens=result.cache_write_tokens,
                        cost_usd=result.cost_usd,
                        latency_ms=result.latency_ms,
                    )

                logger.info("Call succeeded: %d in / %d out / $%.6f / %dms",
                            result.input_tokens, result.output_tokens,
                            result.cost_usd, result.latency_ms)
                return result

            except anthropic.RateLimitError as e:
                wait = self.RETRY_DELAY_BASE ** attempt
                logger.warning("Rate limited (attempt %d/%d), waiting %.1fs: %s",
                               attempt, self.MAX_RETRIES, wait, e)
                if attempt < self.MAX_RETRIES:
                    time.sleep(wait)
                last_error = e

            except (anthropic.APIError, anthropic.APIConnectionError) as e:
                if attempt < self.MAX_RETRIES:
                    wait = self.RETRY_DELAY_BASE ** attempt
                    logger.warning("API error (attempt %d/%d), retrying in %.1fs: %s",
                                   attempt, self.MAX_RETRIES, wait, e)
                    time.sleep(wait)
                last_error = e

        latency_ms = int((time.monotonic() - start_time) * 1000)
        raise RuntimeError(f"LLM call failed after {self.MAX_RETRIES} retries. "
                           f"Last error: {last_error}")

    async def _stream_call(
        self,
        model: str,
        system: list,
        messages: list,
        max_tokens: int,
        temperature: float,
        thinking: Optional[dict],
        extra_headers: Optional[dict],
    ) -> Message:
        """Stream a response and reassemble it into a Message-like object."""
        collected_text = ""
        input_tokens = 0
        output_tokens = 0
        cache_read_tokens = 0
        cache_write_tokens = 0
        stop_reason = "end_turn"

        async with self._client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            temperature=temperature,
            thinking=thinking,
            extra_headers=extra_headers,
        ) as stream:
            async for event in stream:
                if event.type == "message_start":
                    msg = event.message
                    input_tokens = getattr(msg.usage, "input_tokens", 0)
                    cache_read_tokens = getattr(msg.usage, "cache_read_input_tokens", 0)
                    cache_write_tokens = getattr(msg.usage, "cache_creation_input_tokens", 0)
                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        collected_text += event.delta.text
                    elif event.delta.type == "thinking_delta":
                        pass  # Thinking content is not included in final text
                elif event.type == "message_delta":
                    if event.usage:
                        output_tokens = getattr(event.usage, "output_tokens", 0)
                    if event.delta.stop_reason:
                        stop_reason = event.delta.stop_reason

        # Build a Message-like object
        class StreamedMessage:
            class Content:
                def __init__(self, text: str):
                    self.text = text
            class Usage:
                def __init__(self, input_tokens: int, output_tokens: int,
                             cache_read_tokens: int, cache_write_tokens: int):
                    self.input_tokens = input_tokens
                    self.output_tokens = output_tokens
                    self.cache_read_input_tokens = cache_read_tokens
                    self.cache_creation_input_tokens = cache_write_tokens

            def __init__(self, text: str, usage, stop_reason: str):
                self.content = [StreamedMessage.Content(text)]
                self.usage = usage
                self.stop_reason = stop_reason

        return StreamedMessage(
            text=collected_text,
            usage=StreamedMessage.Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
            ),
            stop_reason=stop_reason,
        )

    def _parse_response(self, response: Message, model: str, latency_ms: int) -> LLMResponse:
        """Extract normalized fields from an Anthropic Message response."""
        text = ""
        if response.content:
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text

        # Extract usage
        usage = response.usage
        input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) if usage else 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) if usage else 0

        # Calculate cost
        cost = self._calculate_cost(model, input_tokens, output_tokens, cache_read, cache_write)
        stop_reason = getattr(response, "stop_reason", "end_turn")

        return LLMResponse(
            text=text,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            cost_usd=cost,
            latency_ms=latency_ms,
            stop_reason=stop_reason,
        )

    def _calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_write_tokens: int,
    ) -> float:
        """Calculate cost in USD based on model pricing."""
        pricing = self.PRICING.get(model)
        if not pricing:
            # Unknown model — use Sonnet pricing as default
            pricing = self.PRICING["claude-sonnet-4-6-20250514"]

        # Input tokens: total input minus what was read from cache
        fresh_input = max(0, input_tokens - cache_read_tokens)
        cost = 0.0
        cost += (fresh_input / 1_000_000) * pricing["input"]
        cost += (output_tokens / 1_000_000) * pricing["output"]
        cost += (cache_read_tokens / 1_000_000) * pricing["cache_read"]
        cost += (cache_write_tokens / 1_000_000) * pricing["cache_write"]
        return cost

    def get_pricing(self, model: str) -> dict:
        """Get the pricing dict for a model."""
        return self.PRICING.get(model, self.PRICING["claude-sonnet-4-6-20250514"])
