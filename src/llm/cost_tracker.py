"""API cost tracking and budget management."""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class CostTracker:
    """Tracks LLM API costs with budget monitoring and alerts."""

    def __init__(self, monthly_budget_usd: float = 25.00, alert_threshold: float = 0.8):
        self.monthly_budget_usd = monthly_budget_usd
        self.alert_threshold = alert_threshold

        # Accumulators
        self._total_cost: float = 0.0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_cache_read_tokens: int = 0
        self._total_cache_write_tokens: int = 0
        self._calls: int = 0

        # Per-model tracking
        self._cost_by_model: dict[str, float] = defaultdict(float)
        self._calls_by_model: dict[str, int] = defaultdict(int)

        # History for reporting
        self._entries: list[dict] = []
        self._reset_date: datetime = datetime.utcnow()

    def record(
        self,
        stage: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_write_tokens: int,
        cost_usd: float,
        latency_ms: int,
    ) -> None:
        """Record a single API call."""
        self._total_cost += cost_usd
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        self._total_cache_read_tokens += cache_read_tokens
        self._total_cache_write_tokens += cache_write_tokens
        self._calls += 1
        self._cost_by_model[model] += cost_usd
        self._calls_by_model[model] += 1

        self._entries.append({
            "timestamp": datetime.utcnow().isoformat(),
            "stage": stage,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_write_tokens,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
        })

        # Check budget alert
        if self._total_cost > self.monthly_budget_usd * self.alert_threshold:
            logger.warning(
                "⚠️ Cost alert: $%.4f spent (%.1f%% of $%.2f monthly budget)",
                self._total_cost,
                (self._total_cost / self.monthly_budget_usd) * 100,
                self.monthly_budget_usd,
            )

    @property
    def total_cost(self) -> float:
        return self._total_cost

    @property
    def remaining_budget(self) -> float:
        return max(0.0, self.monthly_budget_usd - self._total_cost)

    @property
    def budget_percent(self) -> float:
        return (self._total_cost / self.monthly_budget_usd) * 100 if self.monthly_budget_usd > 0 else 0

    def get_summary(self) -> dict:
        """Get a cost summary report."""
        return {
            "total_cost_usd": round(self._total_cost, 4),
            "total_calls": self._calls,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_cache_read_tokens": self._total_cache_read_tokens,
            "total_cache_write_tokens": self._total_cache_write_tokens,
            "cache_hit_rate": (
                self._total_cache_read_tokens / max(1, self._total_input_tokens)
            ),
            "monthly_budget_usd": self.monthly_budget_usd,
            "remaining_budget_usd": round(self.remaining_budget, 4),
            "budget_percent": round(self.budget_percent, 1),
            "cost_by_model": dict(self._cost_by_model),
            "calls_by_model": dict(self._calls_by_model),
        }

    def reset_monthly(self) -> None:
        """Reset the monthly counters."""
        self._total_cost = 0.0
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cache_read_tokens = 0
        self._total_cache_write_tokens = 0
        self._calls = 0
        self._cost_by_model.clear()
        self._calls_by_model.clear()
        self._entries.clear()
        self._reset_date = datetime.utcnow()
        logger.info("Monthly cost counters reset")
