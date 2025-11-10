"""Backtest-specific tests."""

import pandas as pd
import pytest

from trading_ai.backtest.engine import BacktestRunner
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


def test_backtest_runner_uses_directional_quotes() -> None:
    context = StrategyContext(
        ticker="AAPL",
        underlying_bars=pd.DataFrame({"close": [100.0, 101.0]}),
        option_chain={},
        option_metrics={},
        option_quote={
            "CALL": {"bid": 1.0, "ask": 2.0},
            "PUT": {"bid": 0.5, "ask": 0.7},
        },
        news_items=[],
        features={},
    )

    runner = BacktestRunner(strategy=AlwaysCallStrategy())
    result = runner.run([context])

    assert result.stats["num_trades"] == 1
    assert result.trades[0].entry_price == 1.5


def test_backtest_runner_exit_prices_reflect_underlying_move() -> None:
    context = StrategyContext(
        ticker="AAPL",
        underlying_bars=pd.DataFrame({"close": [100.0, 105.0]}),
        option_chain={},
        option_metrics={"call": {"contract_type": "call", "open_interest": 100, "greeks": {"delta": 0.6}}},
        option_quote={
            "CALL": {"bid": 1.0, "ask": 2.0},
            "PUT": {"bid": 0.5, "ask": 0.7},
        },
        news_items=[],
        features={},
        option_aggregates={"CALL": [{"close": 2.5}, {"close": 3.0}], "PUT": []},
    )
    runner = BacktestRunner(strategy=AlwaysCallStrategy())

    result = runner.run([context])

    trade = result.trades[0]
    assert trade.exit_price == pytest.approx(3.0)


def test_backtest_runner_puts_gain_when_underlying_falls() -> None:
    context = StrategyContext(
        ticker="AAPL",
        underlying_bars=pd.DataFrame({"close": [100.0, 94.0]}),
        option_chain={},
        option_metrics={"put": {"contract_type": "put", "open_interest": 100, "greeks": {"delta": -0.5}}},
        option_quote={
            "CALL": {"bid": 1.0, "ask": 1.2},
            "PUT": {"bid": 0.9, "ask": 1.1},
        },
        news_items=[],
        features={},
    )
    runner = BacktestRunner(strategy=AlwaysPutStrategy())

    result = runner.run([context])

    trade = result.trades[0]
    assert trade.exit_price > trade.entry_price
