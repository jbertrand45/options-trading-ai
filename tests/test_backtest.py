"""Backtest-specific tests."""

import pandas as pd
import pytest

from trading_ai.backtest.engine import BacktestRunner
from trading_ai.risk.manager import RiskManager
from trading_ai.strategies.base import StrategyContext, TradingSignal, TradingStrategy


class AlwaysCallStrategy(TradingStrategy):
    name = "always_call"

    def generate_signal(self, context: StrategyContext) -> TradingSignal:
        return TradingSignal(
            ticker=context.ticker,
            direction="CALL",
            confidence=0.9,
        )


class AlwaysPutStrategy(TradingStrategy):
    name = "always_put"

    def generate_signal(self, context: StrategyContext) -> TradingSignal:
        return TradingSignal(
            ticker=context.ticker,
            direction="PUT",
            confidence=0.9,
        )


class SequenceStrategy(TradingStrategy):
    """Returns a predetermined sequence of signals for backtest validation."""

    def __init__(self, signals: list[TradingSignal]) -> None:
        self._signals = list(signals)

    def generate_signal(self, context: StrategyContext) -> TradingSignal:
        if not self._signals:
            raise AssertionError("SequenceStrategy ran out of signals")
        return self._signals.pop(0)


def _runner(strategy: TradingStrategy) -> BacktestRunner:
    return BacktestRunner(strategy=strategy, risk_manager=RiskManager(min_liquidity=0.0, max_spread_pct=1.0))


def test_backtest_runner_uses_directional_quotes() -> None:
    context = StrategyContext(
        ticker="AAPL",
        underlying_bars=pd.DataFrame(),
        option_chain={},
        option_metrics={},
        option_quote={
            "CALL": {"bid": 1.0, "ask": 1.1},
            "PUT": {"bid": 0.5, "ask": 0.55},
        },
        news_items=[],
        features={},
    )

    runner = _runner(AlwaysCallStrategy())
    result = runner.run([context])

    assert result.stats["num_trades"] == 1
    assert result.trades[0].entry_price == pytest.approx(1.05)


def test_backtest_runner_exit_prices_follow_option_aggregates() -> None:
    context = StrategyContext(
        ticker="AAPL",
        underlying_bars=pd.DataFrame(),
        option_chain={},
        option_metrics={"call": {"contract_type": "call", "open_interest": 100, "greeks": {"delta": 0.6}}},
        option_quote={
            "CALL": {"bid": 1.0, "ask": 1.15},
            "PUT": {"bid": 0.5, "ask": 0.6},
        },
        news_items=[],
        features={},
        option_aggregates={"CALL": [{"close": 2.5}, {"close": 3.0}], "PUT": []},
    )
    runner = _runner(AlwaysCallStrategy())

    result = runner.run([context])

    trade = result.trades[0]
    assert trade.exit_price == pytest.approx(3.0)


def test_backtest_runner_puts_gain_with_positive_option_bias() -> None:
    context = StrategyContext(
        ticker="AAPL",
        underlying_bars=pd.DataFrame(),
        option_chain={},
        option_metrics={"put": {"contract_type": "put", "open_interest": 100, "greeks": {"delta": -0.5}}},
        option_quote={
            "CALL": {"bid": 1.0, "ask": 1.2},
            "PUT": {"bid": 0.9, "ask": 1.1},
        },
        news_items=[],
        features={},
        option_aggregates={"PUT": [{"close": 1.2}, {"close": 1.5}]},
    )
    signal = TradingSignal(ticker="AAPL", direction="PUT", confidence=0.9, metadata={"option_agg_momentum": -0.04})
    runner = _runner(SequenceStrategy([signal]))

    result = runner.run([context])

    trade = result.trades[0]
    assert trade.exit_price > trade.entry_price


def test_backtest_runner_calls_respect_stop_with_negative_bias() -> None:
    context = StrategyContext(
        ticker="AAPL",
        underlying_bars=pd.DataFrame(),
        option_chain={},
        option_metrics={},
        option_quote={
            "CALL": {"bid": 1.0, "ask": 1.3},
            "PUT": {"bid": 0.8, "ask": 1.0},
        },
        news_items=[],
        features={},
        option_aggregates={},
    )
    signal = TradingSignal(
        ticker="AAPL",
        direction="CALL",
        confidence=0.6,
        metadata={"option_agg_momentum": -0.05, "option_agg_vwap": -0.02},
    )
    runner = _runner(SequenceStrategy([signal]))

    result = runner.run([context])

    trade = result.trades[0]
    assert trade.exit_price < trade.entry_price


def test_backtest_runner_exit_targets_scale_with_confidence() -> None:
    def _context() -> StrategyContext:
        return StrategyContext(
            ticker="AAPL",
            underlying_bars=pd.DataFrame(),
            option_chain={},
            option_metrics={},
            option_quote={
                "CALL": {"bid": 1.5, "ask": 1.8},
                "PUT": {"bid": 0.7, "ask": 0.9},
            },
            news_items=[],
            features={},
            option_aggregates={},
        )

    contexts = [_context(), _context()]
    signals = [
        TradingSignal(ticker="AAPL", direction="CALL", confidence=0.55, metadata={"option_agg_momentum": 0.0}),
        TradingSignal(
            ticker="AAPL",
            direction="CALL",
            confidence=0.95,
            metadata={"option_agg_momentum": 0.04, "option_agg_vwap": 0.02},
        ),
    ]
    runner = _runner(SequenceStrategy(signals))

    result = runner.run(contexts)

    assert result.stats["num_trades"] == 2
    low_confidence_trade, high_confidence_trade = result.trades
    assert high_confidence_trade.exit_price > low_confidence_trade.exit_price
