"""Strategy-layer unit tests."""

import pandas as pd

from trading_ai.strategies.momentum_iv import MomentumIVStrategy
from trading_ai.strategies.base import StrategyContext


def test_momentum_iv_strategy_uses_feature_fallback() -> None:
    strategy = MomentumIVStrategy()
    context = StrategyContext(
        ticker="AAPL",
        underlying_bars=pd.DataFrame(),  # empty bars
        option_chain={},
        option_metrics={},
        option_quote={},
        news_items=[],
        features={"momentum_15": 0.01},
    )

    signal = strategy.generate_signal(context)

    assert signal.direction == "CALL"
    assert signal.confidence > 0.0


def test_momentum_iv_strategy_uses_option_quote_spread() -> None:
    strategy = MomentumIVStrategy()
    context = StrategyContext(
        ticker="AAPL",
        underlying_bars=pd.DataFrame(),
        option_chain={},
        option_metrics={},
        option_quote={
            "CALL": {"bid": 2.0, "ask": 2.2},
            "PUT": {"bid": 0.5, "ask": 0.6},
        },
        news_items=[],
        features={},
    )

    signal = strategy.generate_signal(context)
    assert signal.direction == "CALL"


def test_momentum_iv_strategy_uses_option_flow_bias() -> None:
    strategy = MomentumIVStrategy()
    context = StrategyContext(
        ticker="AAPL",
        underlying_bars=pd.DataFrame(),
        option_chain={},
        option_metrics={
            "call_leg": {
                "contract_type": "call",
                "open_interest": 200,
                "greeks": {"delta": 0.55},
            },
            "put_leg": {
                "contract_type": "put",
                "open_interest": 50,
                "greeks": {"delta": -0.4},
            },
        },
        option_quote={},
        news_items=[],
        features={},
    )

    signal = strategy.generate_signal(context)

    assert signal.direction == "CALL"
    assert signal.metadata["flow_ratio"] > 0


def test_momentum_iv_strategy_falls_back_to_option_chain_for_flow() -> None:
    strategy = MomentumIVStrategy()
    context = StrategyContext(
        ticker="AAPL",
        underlying_bars=pd.DataFrame(),
        option_chain={
            "TEST240118C00100000": {
                "symbol": "TEST240118C00100000",
                "latest_quote": {"bid_size": 50, "ask_size": 60},
                "greeks": {"delta": 0.6},
            },
            "TEST240118P00100000": {
                "symbol": "TEST240118P00100000",
                "latest_quote": {"bid_size": 5, "ask_size": 10},
                "greeks": {"delta": -0.3},
            },
        },
        option_metrics={},
        option_quote={},
        news_items=[],
        features={},
    )

    signal = strategy.generate_signal(context)

    assert signal.direction == "CALL"
    assert signal.metadata["flow_ratio"] > 0


def test_momentum_iv_strategy_uses_option_aggregates() -> None:
    strategy = MomentumIVStrategy()
    context = StrategyContext(
        ticker="AAPL",
        underlying_bars=pd.DataFrame(),
        option_chain={},
        option_metrics={},
        option_quote={
            "CALL": {"bid": 2.0, "ask": 2.2, "symbol": "AAPL251114C00270000"},
            "PUT": {"bid": 1.0, "ask": 1.1, "symbol": "AAPL251114P00270000"},
        },
        news_items=[],
        features={},
        option_aggregates={
            "CALL": [{"close": 1.0}, {"close": 1.4}],
            "PUT": [{"close": 1.0}, {"close": 0.6}],
        },
    )

    signal = strategy.generate_signal(context)

    assert signal.direction == "CALL"
    assert signal.metadata["option_agg_momentum"] > 0
