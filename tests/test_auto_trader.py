"""AutoTrader service tests."""

from __future__ import annotations

from trading_ai.service.auto_trader import AutoTrader, AutoTraderConfig
from trading_ai.settings import Settings
from trading_ai.strategies.momentum_iv import MomentumIVStrategy


class DummyPipeline:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def collect_market_snapshot(self, **_: object):
        return self.snapshot


class DummyAlpaca:
    def __init__(self) -> None:
        self.calls = []

    def submit_option_order(self, **payload):
        self.calls.append(payload)
        return "order-xyz"


def build_settings(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("POLYGON_API_KEY", "polygon")
    return Settings()


def test_auto_trader_builds_intent_from_snapshot(monkeypatch, tmp_path):
    settings = build_settings(monkeypatch)
    snapshot = {
        "AAPL": {
            "underlying_bars": [
                {"timestamp": 1, "close": 100.0},
                {"timestamp": 2, "close": 101.0},
            ],
            "option_chain": {
                "AAPL240118C00100000": {
                    "symbol": "AAPL240118C00100000",
                    "latest_quote": {"bid_size": 10, "ask_size": 20},
                    "greeks": {"delta": 0.5},
                },
                "AAPL240118P00100000": {
                    "symbol": "AAPL240118P00100000",
                    "latest_quote": {"bid_size": 5, "ask_size": 7},
                    "greeks": {"delta": -0.5},
                },
            },
            "option_metrics": {},
            "option_quote": {
                "CALL": {"bid": 1.0, "ask": 1.2, "symbol": "AAPL240118C00100000"},
                "PUT": {"bid": 0.9, "ask": 1.0, "symbol": "AAPL240118P00100000"},
            },
            "news": [],
            "features": {"momentum_15": 0.02},
        }
    }
    pipeline = DummyPipeline(snapshot)
    trader = AutoTrader(
        settings,
        pipeline=pipeline,
        strategy=MomentumIVStrategy(),
        alpaca_client=DummyAlpaca(),  # type: ignore[arg-type]
        config=AutoTraderConfig(
            min_confidence=0.3,
            dry_run=True,
            account_equity=1000.0,
            log_path=tmp_path / "auto.log",
        ),
    )

    intents = trader.run_once()

    assert len(intents) == 1
    assert intents[0].option_symbol == "AAPL240118C00100000"
    assert intents[0].direction == "CALL"
    assert (tmp_path / "auto.log").exists()


def test_auto_trader_calls_live_path(monkeypatch, tmp_path):
    settings = build_settings(monkeypatch)
    snapshot = {
        "AAPL": {
            "underlying_bars": [
                {"timestamp": 1, "close": 100.0},
                {"timestamp": 2, "close": 101.0},
            ],
            "option_chain": {},
            "option_metrics": {},
            "option_quote": {
                "CALL": {"bid": 1.0, "ask": 1.2, "symbol": "CHAIN"},
            },
            "news": [],
            "features": {"momentum_15": 0.02},
        }
    }
    pipeline = DummyPipeline(snapshot)
    alpaca = DummyAlpaca()
    trader = AutoTrader(
        settings,
        pipeline=pipeline,
        strategy=MomentumIVStrategy(),
        alpaca_client=alpaca,  # type: ignore[arg-type]
        config=AutoTraderConfig(
            min_confidence=0.3,
            dry_run=False,
            account_equity=1000.0,
            log_path=tmp_path / "auto.log",
        ),
    )

    trader.run_once()

    assert alpaca.calls
    assert alpaca.calls[0]["symbol"] == "CHAIN"
