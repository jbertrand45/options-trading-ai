"""Tests for MarketDataCollector caching behaviour."""

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List

import pandas as pd
import pytest

from trading_ai.core.collector import MarketDataCollector
from trading_ai.data.cache import LocalDataCache
from trading_ai.settings import Settings


class DummyBars:
    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df


class DummyAlpaca:
    def __init__(self) -> None:
        self.bar_calls = 0
        self.chain_calls = 0

    def fetch_underlying_bars(self, **_: Any) -> DummyBars:
        self.bar_calls += 1
        frame = pd.DataFrame({"timestamp": [1, 2, 3], "close": [100.0, 101.0, 102.0]})
        return DummyBars(frame)

    def fetch_option_chain(self, **_: Any) -> Dict[str, Dict[str, Any]]:
        self.chain_calls += 1
        return {
            "AAPL251107C00100000": {
                "symbol": "AAPL251107C00100000",
                "latest_quote": {"bid_price": 1.2, "ask_price": 1.4},
            },
            "AAPL251107C00110000": {
                "symbol": "AAPL251107C00110000",
                "latest_quote": {"bid_price": 0.9, "ask_price": 1.05},
            },
            "AAPL251107P00100000": {
                "symbol": "AAPL251107P00100000",
                "latest_quote": {"bid_price": 0.8, "ask_price": 0.95},
            },
            "AAPL251107P00110000": {
                "symbol": "AAPL251107P00110000",
                "latest_quote": {"bid_price": 1.4, "ask_price": 1.55},
            },
        }

    def fetch_latest_trade(self, **_: Any) -> Dict[str, Any]:
        return {"trade": {"timestamp": "2025-11-06T16:00:00Z", "price": 101.0, "size": 5}}


class DummyPolygon:
    def __init__(self) -> None:
        self.calls = 0
        self.bar_calls = 0
        self.contract_calls = 0

    def fetch_reference_news(self, **_: Any) -> Iterable[Dict[str, Any]]:
        self.calls += 1
        yield {"title": "Tech stock rallies", "source": "Polygon"}

    def fetch_equity_bars(self, **_: Any) -> Iterable[Dict[str, Any]]:
        self.bar_calls += 1
        return [{"timestamp": 1, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000}]

    def fetch_option_contracts(self, *args: Any, **kwargs: Any) -> Iterable[Dict[str, Any]]:
        self.contract_calls += 1
        return [
            {
                "ticker": "AAPL251107C00100000",
                "contract_type": "call",
                "strike_price": 100.0,
                "implied_volatility": 0.25,
                "open_interest": 120,
                "greeks": {"delta": 0.5, "gamma": 0.1},
            },
            {
                "ticker": "AAPL251107P00100000",
                "contract_type": "put",
                "strike_price": 100.0,
                "implied_volatility": 0.28,
                "open_interest": 80,
                "greeks": {"delta": -0.5, "gamma": 0.1},
            },
        ]


class DummyAggregator:
    def __init__(self) -> None:
        self.calls = 0
        self.providers = [lambda *args, **kwargs: None]

    def gather(self, ticker: str, since: datetime, limit: int = 50) -> List[Dict[str, Any]]:
        self.calls += 1
        return [{"title": "Breaking: New product", "source": "Aggregator"}]


class EmptyBarsAlpaca(DummyAlpaca):
    def __init__(self) -> None:
        super().__init__()
        self.trade_calls = 0

    def fetch_underlying_bars(self, **_: Any) -> DummyBars:
        self.bar_calls += 1
        return DummyBars(pd.DataFrame())

    def fetch_latest_trade(self, **_: Any) -> Dict[str, Any]:
        self.trade_calls += 1
        return {"trade": {"timestamp": "2025-11-06T16:05:00Z", "price": 100.5, "size": 10}}


class EmptyPolygon(DummyPolygon):
    def fetch_equity_bars(self, **_: Any) -> Iterable[Dict[str, Any]]:
        self.bar_calls += 1
        return []


def build_settings(monkeypatch: pytest.MonkeyPatch, *, use_polygon_bars: bool = True) -> Settings:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("POLYGON_API_KEY", "polygon")
    monkeypatch.setenv("NEWS_API_KEY", "news")
    monkeypatch.setenv("NEWS_SECRET_KEY", "secret")
    monkeypatch.setenv("TARGET_TICKERS", '["AAPL"]')
    monkeypatch.setenv("USE_POLYGON_BARS", "1" if use_polygon_bars else "0")
    return Settings()


def test_market_data_collector_uses_cache(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_settings(monkeypatch)
    cache = LocalDataCache(root=tmp_path / "cache")
    alpaca = DummyAlpaca()
    polygon = DummyPolygon()
    aggregator = DummyAggregator()

    collector = MarketDataCollector(
        settings,
        cache=cache,
        alpaca_client=alpaca,  # type: ignore[arg-type]
        polygon_client=polygon,  # type: ignore[arg-type]
        aggregator=aggregator,  # type: ignore[arg-type]
    )

    result = collector.collect_market_snapshot(
        tickers=["AAPL"],
        lookback=timedelta(days=1),
        news_lookback=timedelta(hours=6),
        timeframe="1Min",
        use_cache=True,
    )

    assert "AAPL" in result
    assert polygon.bar_calls == 1
    assert alpaca.chain_calls == 1
    assert aggregator.calls == 1
    assert not result["AAPL"]["underlying_bars"].empty

    # Second call should reuse cached bars and option chain, but still hit latest quote.
    result_second = collector.collect_market_snapshot(
        tickers=["AAPL"],
        lookback=timedelta(days=1),
        news_lookback=timedelta(hours=6),
        timeframe="1Min",
        use_cache=True,
    )

    assert alpaca.bar_calls == 0
    assert alpaca.chain_calls == 1
    assert aggregator.calls == 1
    assert len(result_second["AAPL"]["news"]) == 1  # cached stories


def test_market_data_collector_selects_reference_quotes(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_settings(monkeypatch)
    cache = LocalDataCache(root=tmp_path / "cache")
    collector = MarketDataCollector(
        settings,
        cache=cache,
        alpaca_client=DummyAlpaca(),  # type: ignore[arg-type]
        polygon_client=DummyPolygon(),  # type: ignore[arg-type]
        aggregator=DummyAggregator(),  # type: ignore[arg-type]
    )

    result = collector.collect_market_snapshot(
        tickers=["AAPL"],
        lookback=timedelta(hours=2),
        news_lookback=timedelta(hours=1),
        timeframe="1Min",
        use_cache=False,
    )

    quotes = result["AAPL"]["option_quote"]
    assert set(quotes.keys()) == {"CALL", "PUT"}
    assert quotes["CALL"]["symbol"].endswith("C00100000")
    assert quotes["PUT"]["symbol"].endswith("P00100000")


def test_market_data_collector_falls_back_to_latest_trade(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_settings(monkeypatch, use_polygon_bars=False)
    cache = LocalDataCache(root=tmp_path / "cache")
    alpaca = EmptyBarsAlpaca()
    polygon = EmptyPolygon()
    collector = MarketDataCollector(
        settings,
        cache=cache,
        alpaca_client=alpaca,  # type: ignore[arg-type]
        polygon_client=polygon,  # type: ignore[arg-type]
        aggregator=DummyAggregator(),  # type: ignore[arg-type]
    )

    result = collector.collect_market_snapshot(
        tickers=["AAPL"],
        lookback=timedelta(hours=1),
        news_lookback=timedelta(minutes=30),
        timeframe="1Min",
        use_cache=False,
    )

    bars = result["AAPL"]["underlying_bars"]
    assert len(bars) == 1
    assert bars.iloc[0]["close"] == pytest.approx(100.5)
    assert alpaca.trade_calls == 1


def test_market_data_collector_collects_option_metrics(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_settings(monkeypatch)
    cache = LocalDataCache(root=tmp_path / "cache")
    collector = MarketDataCollector(
        settings,
        cache=cache,
        alpaca_client=DummyAlpaca(),  # type: ignore[arg-type]
        polygon_client=DummyPolygon(),  # type: ignore[arg-type]
        aggregator=DummyAggregator(),  # type: ignore[arg-type]
    )

    result = collector.collect_market_snapshot(
        tickers=["AAPL"],
        lookback=timedelta(hours=2),
        news_lookback=timedelta(hours=1),
        timeframe="1Min",
        use_cache=False,
    )

    metrics = result["AAPL"]["option_metrics"]
    assert "AAPL251107C00100000" in metrics
    assert metrics["AAPL251107C00100000"]["implied_volatility"] == pytest.approx(0.25)
