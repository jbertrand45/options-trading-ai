"""Risk manager for capital-constrained intraday options trading."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class PositionSizingInput:
    account_equity: float
    trade_risk_fraction: float  # e.g., 0.02 for 2%
    contract_price: float
    confidence: float  # 0-1
    max_positions: int = 1
    spread: float = 0.0
    available_volume: float = 0.0


class RiskManager:
    """Determines position sizing and stop levels under strict capital controls."""

    def __init__(
        self,
        *,
        max_daily_loss_pct: float = 0.03,
        min_confidence: float = 0.2,
        max_spread_pct: float = 0.25,
        min_liquidity: float = 50.0,
    ) -> None:
        self.max_daily_loss_pct = max_daily_loss_pct
        self.min_confidence = min_confidence
        self.max_spread_pct = max_spread_pct
        self.min_liquidity = min_liquidity

    def allowable_risk(self, equity: float) -> float:
        return equity * self.max_daily_loss_pct

    def size_position(self, params: PositionSizingInput) -> int:
        if params.confidence < self.min_confidence:
            return 0
        risk_capital = params.account_equity * min(params.trade_risk_fraction, self.max_daily_loss_pct)
        confidence_scalar = params.confidence ** 0.5  # smooth
        spread_scalar = 1.0
        if params.contract_price > 0 and params.spread > 0 and self.max_spread_pct > 0:
            spread_pct = params.spread / params.contract_price
            if spread_pct > self.max_spread_pct:
                return 0
            spread_scalar = max(0.0, 1.0 - (spread_pct / self.max_spread_pct))
        liquidity_scalar = 1.0
        if self.min_liquidity > 0:
            if params.available_volume <= 0:
                return 0
            liquidity_scalar = min(1.0, params.available_volume / self.min_liquidity)
        budget = risk_capital * confidence_scalar * spread_scalar * liquidity_scalar
        if params.contract_price <= 0:
            return 0
        qty = int(budget // params.contract_price)
        return max(0, min(qty, params.max_positions))

    def stop_loss_price(self, entry_price: float, risk_fraction: float) -> float:
        return max(0.01, entry_price * (1 - risk_fraction))

    def take_profit_price(self, entry_price: float, reward_multiplier: float = 2.0, risk_fraction: float = 0.2) -> float:
        return entry_price * (1 + reward_multiplier * risk_fraction)
