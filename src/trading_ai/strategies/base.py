"""Core abstractions for trading strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd


@dataclass
class TradingSignal:
    """Represents an actionable decision produced by a strategy."""

    ticker: str
    direction: str  # "CALL", "PUT", "NONE"
    confidence: float
    entry_price: Optional[float] = None
    target_price: Optional[float] = None
    stop_price: Optional[float] = None
    metadata: Dict[str, Any] | None = None


@dataclass
class StrategyContext:
    """Bundle of inputs needed to evaluate a strategy for a specific ticker."""

    ticker: str
    underlying_bars: pd.DataFrame
    option_chain: Any
    option_quote: Any
    news_items: list[Dict[str, Any]]
    features: Dict[str, Any] | None = None


class TradingStrategy:
    """Base class; concrete strategies implement `generate_signal`."""

    name: str = "base"

    def generate_signal(self, context: StrategyContext) -> TradingSignal:
        raise NotImplementedError
