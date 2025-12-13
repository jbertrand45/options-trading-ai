"""CLI parser tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from trading_ai.cli import build_parser, command_auto_trade
from trading_ai.settings import Settings


def test_auto_trade_parser_supports_snapshot_stream_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "auto-trade",
            "--use-snapshot-stream",
            "--stream-interval",
            "45",
            "--stream-force-refresh",
        ]
    )

    assert args.use_snapshot_stream is True
    assert args.stream_interval == 45
    assert args.stream_force_refresh is True


def test_auto_trade_parser_accepts_risk_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "auto-trade",
            "--max-option-spread-pct",
            "0.4",
            "--min-option-liquidity",
            "10",
        ]
    )
    assert args.max_option_spread_pct == pytest.approx(0.4)
    assert args.min_option_liquidity == pytest.approx(10.0)


def test_command_auto_trade_uses_env_option_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("MIN_OPTION_AGG_BARS", "30")
    monkeypatch.setenv("MIN_OPTION_AGG_VOLUME", "222.2")
    monkeypatch.setenv("MIN_OPTION_AGG_VWAP", "0.06")
    settings = Settings()
    monkeypatch.setattr("trading_ai.cli.get_settings", lambda: settings)

    class DummyTrader:
        last_config = None

        def __init__(self, *_: object, config, **__: object) -> None:
            DummyTrader.last_config = config

        def run_once(self):
            return []

        def close(self):
            pass

    monkeypatch.setattr("trading_ai.cli.AutoTrader", DummyTrader)
    monkeypatch.setattr("trading_ai.cli.SignalPipeline", lambda *_: object())
    monkeypatch.setattr("trading_ai.cli.MomentumIVStrategy", lambda *_: object())
    def _risk_manager(*_: object, **__: object) -> object:
        return object()

    monkeypatch.setattr("trading_ai.cli.RiskManager", _risk_manager)

    args = SimpleNamespace(
        lookback_minutes=120,
        news_hours=3,
        timeframe="1Min",
        min_confidence=None,
        risk_fraction=None,
        max_positions=None,
        account_equity=None,
        min_option_agg_bars=None,
        min_option_agg_volume=None,
        min_option_agg_vwap=None,
        max_option_spread_pct=0.4,
        min_option_liquidity=10.0,
        stop_loss_fraction=None,
        take_profit_reward=None,
        option_order_mode=None,
        include_news=None,
        use_cache=None,
        use_snapshot_stream=None,
        use_live_stream=None,
        stream_interval=None,
        stream_force_refresh=None,
        loop=False,
        interval=None,
        live=False,
    )

    command_auto_trade(args)

    assert DummyTrader.last_config is not None
    assert DummyTrader.last_config.min_option_agg_bars == 30
    assert DummyTrader.last_config.min_option_agg_volume == pytest.approx(222.2)
    assert DummyTrader.last_config.min_option_agg_vwap == pytest.approx(0.06)
