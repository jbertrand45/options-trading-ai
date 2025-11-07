"""Momentum + Implied Volatility strategy scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd

from trading_ai.strategies.base import StrategyContext, TradingSignal, TradingStrategy


@dataclass
class MomentumIVConfig:
    lookback_minutes: int = 60
    momentum_threshold: float = 0.003  # 0.3%
    iv_squeeze_threshold: float = -0.05  # 5% drop vs. rolling IV mean
    max_confidence: float = 0.9


class MomentumIVStrategy(TradingStrategy):
    """Blend of intraday momentum and IV crush detection."""

    name = "momentum_iv"

    def __init__(self, config: Optional[MomentumIVConfig] = None) -> None:
        self.config = config or MomentumIVConfig()

    def _compute_momentum(self, bars: pd.DataFrame) -> float:
        if bars.empty:
            return 0.0
        close = bars["close"].astype(float)
        window = close.tail(self.config.lookback_minutes)
        if len(window) < 2:
            return 0.0
        return (window.iloc[-1] - window.iloc[0]) / window.iloc[0]

    def _extract_iv_metrics(self, option_chain: Dict) -> Dict[str, float]:
        if not option_chain:
            return {"avg_iv": np.nan, "iv_change": np.nan}
        ivs = []
        iv_changes = []
        for leg in option_chain if isinstance(option_chain, list) else option_chain.values():
            if isinstance(leg, dict):
                iv = leg.get("implied_volatility")
                if iv is not None:
                    ivs.append(float(iv))
                iv_change = leg.get("iv_change")
                if iv_change is not None:
                    iv_changes.append(float(iv_change))
        return {
            "avg_iv": float(np.nanmean(ivs)) if ivs else np.nan,
            "iv_change": float(np.nanmean(iv_changes)) if iv_changes else np.nan,
        }

    def _determine_direction(self, momentum: float, iv_change: float) -> str:
        if momentum > self.config.momentum_threshold and iv_change <= self.config.iv_squeeze_threshold:
            return "CALL"
        if momentum < -self.config.momentum_threshold and iv_change >= -self.config.iv_squeeze_threshold:
            return "PUT"
        if momentum > self.config.momentum_threshold:
            return "CALL"
        if momentum < -self.config.momentum_threshold:
            return "PUT"
        return "NONE"

    def _confidence_score(self, momentum: float, iv_change: float, news_bias: float) -> float:
        momentum_score = min(abs(momentum) / (self.config.momentum_threshold * 2), 1.0)
        iv_score = 0.0 if np.isnan(iv_change) else min(abs(iv_change) / 0.1, 1.0)
        raw = 0.5 * momentum_score + 0.3 * iv_score + 0.2 * news_bias
        return max(0.0, min(raw * self.config.max_confidence, self.config.max_confidence))

    def _news_bias(self, news_items: list[dict]) -> float:
        if not news_items:
            return 0.5
        positive = 0
        negative = 0
        for article in news_items:
            summary = str(article.get("description") or article.get("title") or "").lower()
            if any(keyword in summary for keyword in ("beats", "surge", "upgrade", "positive")):
                positive += 1
            if any(keyword in summary for keyword in ("misses", "downgrade", "negative", "lawsuit")):
                negative += 1
        total = positive + negative
        if total == 0:
            return 0.5
        return max(0.0, min(positive / total, 1.0))

    def generate_signal(self, context: StrategyContext) -> TradingSignal:
        bars = context.underlying_bars
        momentum = self._compute_momentum(bars)
        iv_metrics = self._extract_iv_metrics(context.option_chain)
        iv_change = iv_metrics["iv_change"]
        direction = self._determine_direction(momentum, iv_change)
        news_bias = self._news_bias(context.news_items)
        confidence = self._confidence_score(momentum, iv_change, news_bias)

        signal = TradingSignal(
            ticker=context.ticker,
            direction=direction,
            confidence=confidence,
            metadata={
                "momentum": momentum,
                "avg_iv": iv_metrics["avg_iv"],
                "iv_change": iv_change,
                "news_bias": news_bias,
            },
        )
        return signal
