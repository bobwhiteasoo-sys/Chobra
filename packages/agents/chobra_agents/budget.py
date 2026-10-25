"""Run budget with atomic reservations (spec section 12 "Учет расходов").

Before a call the upper bound is reserved; afterwards the reservation is settled with the
provider's usage. Unknown usage keeps the reserved upper bound in a separate
"awaiting reconciliation" bucket so the limit stays safe. All retries reserve separately.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


class BudgetExhausted(Exception):
    pass


@dataclass(frozen=True)
class Price:
    model: str
    input_microusd_per_mtok: int
    output_microusd_per_mtok: int
    currency: str
    source: str
    as_of: str

    def cost_microusd(self, input_tokens: int, output_tokens: int) -> int:
        return (input_tokens * self.input_microusd_per_mtok + output_tokens * self.output_microusd_per_mtok) // 1_000_000


# Anthropic first-party list prices, from the Claude API skill's model table (cached 2026-10-06).
PRICES = {
    "claude-opus-5-5": Price("claude-opus-5-5", 4_000_000, 20_000_000, "USD", "Claude API pricing table", "2026-10-06"),
    "claude-sonnet-5-5": Price("claude-sonnet-5-5", 2_000_000, 10_000_000, "USD", "Claude API pricing table", "2026-10-06"),
    "claude-haiku-5-5": Price("claude-haiku-5-5", 100_000, 500_000, "USD", "Claude API pricing table", "2026-10-06"),
    "claude-fable-5-1": Price("claude-fable-5-1", 10_000_000, 50_000_000, "USD", "Claude API pricing table", "2026-10-06"),
}


class RunBudget:
    def __init__(
        self,
        *,
        max_calls: int,
        max_input_tokens: int | None = None,
        max_output_tokens: int | None = None,
        money_limit_microusd: int | None = None,
        price: Price | None = None,
    ):
        if money_limit_microusd is not None and price is None:
            raise ValueError("Денежный предел нельзя гарантировать без действующей таблицы цен (AC-038)")
        self.max_calls = max_calls
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.money_limit = money_limit_microusd
        self.price = price
        self._lock = threading.Lock()
        self.calls = 0
        self.reserved_input = 0
        self.reserved_output = 0
        self.used_input = 0
        self.used_output = 0
        self.unknown_calls = 0
        self.open: dict[int, tuple[int, int]] = {}
        self._next = 0

    def _cost(self, input_tokens: int, output_tokens: int) -> int:
        return self.price.cost_microusd(input_tokens, output_tokens) if self.price else 0

    def reserve(self, *, input_tokens: int, output_tokens: int) -> int:
        with self._lock:
            if self.calls + 1 > self.max_calls:
                raise BudgetExhausted("calls")
            total_in = self.used_input + self.reserved_input + input_tokens
            total_out = self.used_output + self.reserved_output + output_tokens
            if self.max_input_tokens is not None and total_in > self.max_input_tokens:
                raise BudgetExhausted("input_tokens")
            if self.max_output_tokens is not None and total_out > self.max_output_tokens:
                raise BudgetExhausted("output_tokens")
            if self.money_limit is not None and self._cost(total_in, total_out) > self.money_limit:
                raise BudgetExhausted("money")
            self.calls += 1
            self.reserved_input += input_tokens
            self.reserved_output += output_tokens
            self._next += 1
            self.open[self._next] = (input_tokens, output_tokens)
            return self._next

    def settle(self, token: int, usage: dict[str, int] | None) -> None:
        with self._lock:
            reserved = self.open.pop(token, None)
            if reserved is None:
                return
            if usage is None:
                # Unknown usage: keep the upper bound as spent until reconciliation.
                self.unknown_calls += 1
                self.used_input += reserved[0]
                self.used_output += reserved[1]
            else:
                self.used_input += usage.get("input_tokens", 0)
                self.used_output += usage.get("output_tokens", 0)
            self.reserved_input -= reserved[0]
            self.reserved_output -= reserved[1]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "calls": self.calls,
                "max_calls": self.max_calls,
                "input_tokens": self.used_input,
                "output_tokens": self.used_output,
                "reserved_input_tokens": self.reserved_input,
                "reserved_output_tokens": self.reserved_output,
                "unknown_usage_calls": self.unknown_calls,
                "known_cost_microusd": self._cost(self.used_input, self.used_output) if self.price else None,
                "currency": self.price.currency if self.price else None,
                "price_source": f"{self.price.source}, {self.price.as_of}" if self.price else None,
            }
