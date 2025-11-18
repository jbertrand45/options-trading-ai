"""Lightweight backtesting harness (placeholder for deeper research)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from trading_ai.risk.manager import PositionSizingInput, RiskManager
from trading_ai.strategies.base import StrategyContext, TradingSignal, TradingStrategy


@dataclass
class BacktestConfig:
    starting_equity: float = 150.0
    risk_fraction: float = 0.02
    commission_per_contract: float = 0.65
    max_positions: int = 1
    min_confidence: float = 0.5
    min_contract_price: float = 0.3
    base_take_profit_pct: float = 0.5
    base_stop_loss_pct: float = 0.35
    min_reward_pct: float = 0.15
    min_stop_pct: float = 0.15
    volatility_target_weight: float = 1.2
    volatility_stop_weight: float = 0.8
    range_target_weight: float = 0.6
    agg_exit_weight: float = 0.5
    option_exit_lookback: int = 12
    floor_price_pct: float = 0.05


@dataclass
class TradeRecord:
    ticker: str
    direction: str
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    confidence: float
    metadata: Dict[str, float] = field(default_factory=dict)


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: List[TradeRecord]
    stats: Dict[str, float]


class BacktestRunner:
    """Executes a strategy over historical snapshots."""

    def __init__(self, strategy: TradingStrategy, risk_manager: Optional[RiskManager] = None, config: Optional[BacktestConfig] = None) -> None:
        self.strategy = strategy
        self.risk_manager = risk_manager or RiskManager()
        self.config = config or BacktestConfig()

    def run(self, snapshots: Iterable[StrategyContext]) -> BacktestResult:
        equity = self.config.starting_equity
        equity_points: List[float] = []
        trades: List[TradeRecord] = []

        for context in snapshots:
            signal = self.strategy.generate_signal(context)
            if signal.direction == "NONE" or signal.confidence <= 0:
                equity_points.append(equity)
                continue
            if signal.confidence < self.config.min_confidence:
                equity_points.append(equity)
                continue

            entry_price = self._infer_entry_price(signal, context)
            if entry_price is None or entry_price < self.config.min_contract_price:
                equity_points.append(equity)
                continue

            spread = self._quote_spread(context, signal.direction)
            available_volume = self._aggregate_volume(context, signal.direction)
            size = self.risk_manager.size_position(
                PositionSizingInput(
                    account_equity=equity,
                    trade_risk_fraction=self.config.risk_fraction,
                    contract_price=entry_price,
                    confidence=signal.confidence,
                    max_positions=self.config.max_positions,
                    spread=spread,
                    available_volume=available_volume,
                )
            )
            if size == 0:
                equity_points.append(equity)
                continue

            exit_price = self._simulate_exit_price(signal, context, entry_price)
            pnl = (exit_price - entry_price) * size
            if signal.direction == "PUT":
                pnl *= -1

            pnl -= self.config.commission_per_contract * size * 2  # round-trip cost
            equity += pnl
            equity_points.append(equity)
            trades.append(
                TradeRecord(
                    ticker=signal.ticker,
                    direction=signal.direction,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    quantity=size,
                    pnl=pnl,
                    confidence=signal.confidence,
                    metadata=signal.metadata or {},
                )
            )

        equity_series = pd.Series(equity_points)
        stats = {
            "final_equity": equity,
            "return_pct": (equity / self.config.starting_equity) - 1,
            "max_drawdown": self._max_drawdown(equity_series),
            "num_trades": len(trades),
        }
        return BacktestResult(equity_curve=equity_series, trades=trades, stats=stats)

    def _infer_entry_price(self, signal: TradingSignal, context: StrategyContext) -> Optional[float]:
        if signal.entry_price:
            return signal.entry_price
        quote = context.option_quote
        if isinstance(quote, dict) and ("CALL" in quote or "PUT" in quote):
            quote = quote.get(signal.direction) or quote.get("CALL") or quote.get("PUT")
        bid = None
        ask = None
        if isinstance(quote, dict):
            bid = quote.get("bid", quote.get("bid_price"))
            ask = quote.get("ask", quote.get("ask_price"))
        if bid is None or ask is None:
            return None
        mid = (float(bid) + float(ask)) / 2
        return mid

    def _simulate_exit_price(self, signal: TradingSignal, context: StrategyContext, entry_price: float) -> float:
        if signal.target_price:
            return signal.target_price

        agg_exit = self._option_aggregate_exit(signal, context, entry_price)
        if agg_exit is not None:
            return agg_exit

        option_vol = self._option_volatility(context, signal.direction)
        option_range = self._option_range_pct(context, signal.direction)
        metadata_bias = self._metadata_exit_bias(signal)
        confidence = max(self.config.min_confidence, signal.confidence)
        target_pct = (
            self.config.base_take_profit_pct * confidence
            + option_range * self.config.range_target_weight
            + max(0.0, metadata_bias)
        )
        stop_pct = (
            self.config.base_stop_loss_pct / max(confidence, 0.5)
            + option_vol * self.config.volatility_stop_weight
            + max(0.0, -metadata_bias)
        )
        target_pct = max(self.config.min_reward_pct, target_pct)
        stop_pct = max(self.config.min_stop_pct, stop_pct)

        upper = entry_price * (1 + target_pct)
        lower = entry_price * (1 - stop_pct)
        floor_price = entry_price * self.config.floor_price_pct
        lower = max(lower, floor_price)

        projected_exit = entry_price * (1 + metadata_bias)
        projected_exit = max(lower, min(upper, projected_exit))
        return max(projected_exit, 0.01)


    def _option_aggregate_exit(self, signal: TradingSignal, context: StrategyContext, entry_price: float) -> Optional[float]:
        aggs = context.option_aggregates or {}
        leg_series = aggs.get(signal.direction)
        if not isinstance(leg_series, list) or not leg_series:
            return None
        closes = [bar.get("close") for bar in leg_series if isinstance(bar, dict) and bar.get("close") is not None]
        if not closes:
            return None
        try:
            exit_price = float(closes[-1])
        except (TypeError, ValueError):
            return None
        return max(exit_price, 0.01)

    def _option_volatility(self, context: StrategyContext, direction: str) -> float:
        aggs = context.option_aggregates or {}
        series = aggs.get(direction) or []
        if not isinstance(series, list):
            return 0.0
        closes = [
            self._safe_float(bar.get("close"))
            for bar in series[-self.config.option_exit_lookback :]
            if isinstance(bar, dict) and bar.get("close") is not None
        ]
        if len(closes) < 2:
            return 0.0
        closes_arr = np.asarray(closes, dtype=float)
        prev = closes_arr[:-1]
        diff = np.diff(closes_arr)
        valid = prev != 0
        if not valid.any():
            return 0.0
        returns = diff[valid] / prev[valid]
        if returns.size == 0:
            return 0.0
        return float(np.std(returns))

    def _option_range_pct(self, context: StrategyContext, direction: str) -> float:
        aggs = context.option_aggregates or {}
        series = aggs.get(direction) or []
        if not isinstance(series, list):
            return 0.0
        closes = [
            self._safe_float(bar.get("close"))
            for bar in series[-self.config.option_exit_lookback :]
            if isinstance(bar, dict) and bar.get("close") is not None
        ]
        if len(closes) < 2:
            return 0.0
        latest = closes[-1]
        if latest <= 0:
            return 0.0
        return float((max(closes) - min(closes)) / latest)

    def _quote_spread(self, context: StrategyContext, direction: str) -> float:
        quote = context.option_quote
        if isinstance(quote, dict):
            leg = quote.get(direction) or quote.get(direction.capitalize())
            if isinstance(leg, dict):
                bid = leg.get("bid") or leg.get("bid_price")
                ask = leg.get("ask") or leg.get("ask_price")
                try:
                    bid_f = float(bid) if bid is not None else None
                    ask_f = float(ask) if ask is not None else None
                except (TypeError, ValueError):
                    return 0.0
                if bid_f is None or ask_f is None:
                    return 0.0
                return max(0.0, ask_f - bid_f)
        return 0.0

    def _aggregate_volume(self, context: StrategyContext, direction: str) -> float:
        aggs = context.option_aggregates or {}
        series = aggs.get(direction) or []
        if not isinstance(series, list):
            return 0.0
        volume = 0.0
        for bar in series[-self.config.option_exit_lookback :]:
            if isinstance(bar, dict):
                try:
                    volume += float(bar.get("volume") or 0.0)
                except (TypeError, ValueError):
                    continue
        return volume

    def _metadata_exit_bias(self, signal: TradingSignal) -> float:
        metadata = signal.metadata or {}
        agg_momentum = self._safe_float(metadata.get("option_agg_momentum"))
        agg_vwap = self._safe_float(metadata.get("option_agg_vwap"))
        vega_bias = self._safe_float(metadata.get("vega_bias"))
        theta_bias = self._safe_float(metadata.get("theta_bias"))
        bias = agg_momentum + agg_vwap + 0.5 * vega_bias - 0.25 * abs(theta_bias)
        return bias * self.config.agg_exit_weight

    def _safe_float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _max_drawdown(self, equity: pd.Series) -> float:
        running_max = equity.cummax()
        drawdown = (equity - running_max) / running_max
        return abs(drawdown.min()) if not drawdown.empty else 0.0
