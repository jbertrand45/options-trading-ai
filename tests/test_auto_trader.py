"""AutoTrader service tests."""

from __future__ import annotations

from trading_ai.risk.manager import RiskManager
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

    def get_account_equity(self) -> float:
        return 1000.0

    def option_is_tradable(self, symbol: str) -> bool:  # pragma: no cover - trivial stub
        return True


class DummyStream:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.refresh_calls = 0

    def latest_snapshot(self):
        return {} if self.refresh_calls == 0 else self.snapshot

    def refresh_now(self):
        self.refresh_calls += 1
        return self.snapshot


class FailingStream(DummyStream):
    def refresh_now(self):
        self.refresh_calls += 1
        raise RuntimeError("boom")


def build_settings(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    return Settings()


def build_risk_manager() -> RiskManager:
    return RiskManager(min_confidence=0.3, max_spread_pct=1.0, min_liquidity=0.0)


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
            "option_aggregates": {
                "CALL": [{"close": 1.1, "volume": 5, "vwap": 1.1 + i * 0.01} for i in range(20)],
                "PUT": [{"close": 0.9, "volume": 3, "vwap": 0.9 - i * 0.01} for i in range(20)],
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
        risk_manager=build_risk_manager(),
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
    assert intents[0].metadata["option_agg_volume"] > 0
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
            "option_aggregates": {
                "CALL": [{"close": 1.1, "volume": 5, "vwap": 1.0 + i * 0.02} for i in range(15)],
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
        risk_manager=build_risk_manager(),
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


def test_auto_trader_respects_option_aggregate_threshold(monkeypatch, tmp_path):
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
            "option_aggregates": {
                "CALL": [{"close": 1.1, "volume": 1, "vwap": 1.0}] * 2,
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
        risk_manager=build_risk_manager(),
        config=AutoTraderConfig(
            min_confidence=0.3,
            dry_run=True,
            account_equity=1000.0,
            log_path=tmp_path / "auto.log",
            min_option_agg_bars=5,
            min_option_agg_volume=10.0,
            min_option_agg_vwap=0.0,
            enable_option_aggregates=True,
        ),
    )

    intents = trader.run_once()

    assert len(intents) == 0


def test_auto_trader_respects_option_agg_vwap(monkeypatch, tmp_path):
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
            "option_aggregates": {
                "CALL": [{"close": 1.1, "volume": 5, "vwap": 1.0}] * 10,
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
        risk_manager=build_risk_manager(),
        config=AutoTraderConfig(
            min_confidence=0.3,
            dry_run=True,
            account_equity=1000.0,
            log_path=tmp_path / "auto.log",
            min_option_agg_vwap=0.05,
            enable_option_aggregates=True,
        ),
    )

    intents = trader.run_once()

    assert len(intents) == 0


def test_auto_trader_uses_snapshot_stream_when_provided(monkeypatch, tmp_path):
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
                "PUT": {"bid": 0.9, "ask": 1.1, "symbol": "OTHER"},
            },
            "option_aggregates": {
                "CALL": [{"close": 1.1, "volume": 5, "vwap": 1.0 + i * 0.02} for i in range(15)],
            },
            "news": [],
            "features": {"momentum_15": 0.02},
        }
    }

    class NoopPipeline:
        def collect_market_snapshot(self, **_):
            raise AssertionError("pipeline should not be invoked when stream present")

    stream = DummyStream(snapshot)
    trader = AutoTrader(
        settings,
        pipeline=NoopPipeline(),  # type: ignore[arg-type]
        strategy=MomentumIVStrategy(),
        alpaca_client=DummyAlpaca(),  # type: ignore[arg-type]
        risk_manager=build_risk_manager(),
        config=AutoTraderConfig(
            min_confidence=0.3,
            dry_run=True,
            account_equity=1000.0,
            log_path=tmp_path / "auto.log",
        ),
        snapshot_stream=stream,
    )

    intents = trader.run_once()

    assert stream.refresh_calls == 1
    assert len(intents) == 1


def test_auto_trader_falls_back_when_stream_refresh_fails(monkeypatch, tmp_path):
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
                "PUT": {"bid": 0.9, "ask": 1.1, "symbol": "OTHER"},
            },
            "option_aggregates": {
                "CALL": [{"close": 1.1, "volume": 5, "vwap": 1.0 + i * 0.02} for i in range(15)],
            },
            "news": [],
            "features": {"momentum_15": 0.02},
        }
    }

    pipeline_called = {"count": 0}

    class CountingPipeline:
        def collect_market_snapshot(self, **_):
            pipeline_called["count"] += 1
            return snapshot

    failing_stream = FailingStream(snapshot)
    trader = AutoTrader(
        settings,
        pipeline=CountingPipeline(),  # type: ignore[arg-type]
        strategy=MomentumIVStrategy(),
        alpaca_client=DummyAlpaca(),  # type: ignore[arg-type]
        risk_manager=build_risk_manager(),
        config=AutoTraderConfig(
            min_confidence=0.3,
            dry_run=True,
            account_equity=1000.0,
            log_path=tmp_path / "auto.log",
            use_snapshot_stream=True,
        ),
        snapshot_stream=failing_stream,
    )

    intents = trader.run_once()

    assert pipeline_called["count"] == 1
    assert failing_stream.refresh_calls == 1
    assert len(intents) == 1
