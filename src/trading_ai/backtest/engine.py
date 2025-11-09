"""Lightweight backtesting harness (placeholder for deeper research)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

import pandas as pd

from trading_ai.risk.manager import PositionSizingInput, RiskManager
from trading_ai.strategies.base import StrategyContext, TradingSignal, TradingStrategy


@dataclass
class BacktestConfig:
    starting_equity: float = 150.0
    risk_fraction: float = 0.02
    commission_per_contract: float = 0.65
    max_positions: int = 1


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

            entry_price = self._infer_entry_price(signal, context)
            if entry_price is None:
                equity_points.append(equity)
                continue

            size = self.risk_manager.size_position(
                PositionSizingInput(
                    account_equity=equity,
                    trade_risk_fraction=self.config.risk_fraction,
                    contract_price=entry_price,
                    confidence=signal.confidence,
                    max_positions=self.config.max_positions,
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
        # Placeholder: simple momentum assumption +/- 20%
        direction = 1 if signal.direction == "CALL" else -1
        return entry_price * (1 + direction * 0.2 * signal.confidence)

    def _max_drawdown(self, equity: pd.Series) -> float:
        running_max = equity.cummax()
        drawdown = (equity - running_max) / running_max
        return abs(drawdown.min()) if not drawdown.empty else 0.0
