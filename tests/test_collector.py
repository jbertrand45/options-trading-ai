"""Tests for MarketDataCollector caching behaviour."""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List

import pandas as pd
import pytest

from trading_ai.clients.base import APIClientError
from trading_ai.core.collector import MarketDataCollector, _regular_session_open_utc
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
        self.agg_calls = 0

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

    def fetch_option_aggregates(self, *args: Any, **kwargs: Any) -> Iterable[Dict[str, Any]]:
        self.agg_calls += 1
        return [
            {
                "timestamp": 1,
                "open": 1.0,
                "high": 1.2,
                "low": 0.9,
                "close": 1.1,
                "volume": 250,
            }
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


class FailingAlpaca(DummyAlpaca):
    def fetch_option_chain(self, **_: Any):
        raise APIClientError("chain down")

    def fetch_option_metrics(self, **_: Any):
        raise APIClientError("metrics down")


class FailingPolygonAgg(DummyPolygon):
    def fetch_option_aggregates(self, *args: Any, **kwargs: Any) -> Iterable[Dict[str, Any]]:
        raise APIClientError("agg down")


def build_settings(monkeypatch: pytest.MonkeyPatch, *, use_polygon_bars: bool = True, enable_option_aggregates: bool = True) -> Settings:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("POLYGON_API_KEY", "polygon")
    monkeypatch.setenv("NEWS_API_KEY", "news")
    monkeypatch.setenv("NEWS_SECRET_KEY", "secret")
    monkeypatch.setenv("TARGET_TICKERS", '["AAPL"]')
    monkeypatch.setenv("USE_POLYGON_BARS", "1" if use_polygon_bars else "0")
    monkeypatch.setenv("ENABLE_OPTION_AGGREGATES", "1" if enable_option_aggregates else "0")
    monkeypatch.setenv("USE_ALPACA_OPTION_CHAIN", "1")
    if "ENABLE_UNDERLYING_BARS" not in os.environ:
        monkeypatch.setenv("ENABLE_UNDERLYING_BARS", "1")
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


def test_market_data_collector_fetches_option_aggregates(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_settings(monkeypatch)
    cache = LocalDataCache(root=tmp_path / "cache")
    polygon = DummyPolygon()
    collector = MarketDataCollector(
        settings,
        cache=cache,
        alpaca_client=DummyAlpaca(),  # type: ignore[arg-type]
        polygon_client=polygon,  # type: ignore[arg-type]
        aggregator=DummyAggregator(),  # type: ignore[arg-type]
    )

    result = collector.collect_market_snapshot(
        tickers=["AAPL"],
        lookback=timedelta(hours=1),
        news_lookback=timedelta(hours=1),
        timeframe="1Min",
        use_cache=False,
    )

    aggs = result["AAPL"]["option_aggregates"]
    assert "CALL" in aggs
    assert aggs["CALL"][0]["close"] == pytest.approx(1.1)
    assert polygon.agg_calls >= 1


def test_option_aggregates_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_settings(monkeypatch, enable_option_aggregates=False)
    polygon = DummyPolygon()
    collector = MarketDataCollector(
        settings,
        cache=LocalDataCache(),
        alpaca_client=DummyAlpaca(),  # type: ignore[arg-type]
        polygon_client=polygon,  # type: ignore[arg-type]
        aggregator=DummyAggregator(),  # type: ignore[arg-type]
    )

    start = datetime.utcnow() - timedelta(minutes=10)
    end = datetime.utcnow()
    option_quote = {"CALL": {"symbol": "TEST"}}

    aggregates = collector.collect_option_aggregates(
        option_quote=option_quote,
        start=start,
        end=end,
        timeframe="1Min",
        use_cache=False,
    )

    assert aggregates == {}
    assert polygon.agg_calls == 0


def test_option_quote_falls_back_to_polygon_metrics(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_settings(monkeypatch)
    cache = LocalDataCache(root=tmp_path / "cache")
    collector = MarketDataCollector(
        settings,
        cache=cache,
        alpaca_client=DummyAlpaca(),  # type: ignore[arg-type]
        polygon_client=DummyPolygon(),  # type: ignore[arg-type]
        aggregator=DummyAggregator(),  # type: ignore[arg-type]
    )
    bars = pd.DataFrame({"close": [100.0, 101.0]})
    metrics = {
        "AAPL251107C00100000": {
            "contract_type": "CALL",
            "strike_price": 101.0,
            "open_interest": 50,
            "expiration_date": "2025-11-20",
            "last_quote": {"bid_price": 1.0, "ask_price": 1.2},
        },
        "AAPL251107P00100000": {
            "contract_type": "PUT",
            "strike_price": 99.0,
            "open_interest": 40,
            "expiration_date": "2025-11-20",
            "last_quote": {"bid_price": 0.9, "ask_price": 1.1},
        },
    }

    quotes = collector.collect_option_quote("AAPL", option_chain=None, option_metrics=metrics, bars=bars)

    assert set(quotes.keys()) == {"CALL", "PUT"}
    assert quotes["CALL"]["source"] == "polygon"
    assert quotes["PUT"]["symbol"] == "AAPL251107P00100000"


def test_collect_market_snapshot_handles_option_chain_failure(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_settings(monkeypatch)
    cache = LocalDataCache(root=tmp_path / "cache")
    collector = MarketDataCollector(
        settings,
        cache=cache,
        alpaca_client=FailingAlpaca(),  # type: ignore[arg-type]
        polygon_client=DummyPolygon(),  # type: ignore[arg-type]
        aggregator=DummyAggregator(),  # type: ignore[arg-type]
    )

    snapshot = collector.collect_market_snapshot(
        tickers=["AAPL"],
        lookback=timedelta(minutes=5),
        news_lookback=timedelta(minutes=5),
        timeframe="1Min",
        use_cache=False,
    )

    assert snapshot["AAPL"]["option_chain"] == {}


def test_collect_market_snapshot_handles_option_aggregate_failure(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_settings(monkeypatch)
    cache = LocalDataCache(root=tmp_path / "cache")
    collector = MarketDataCollector(
        settings,
        cache=cache,
        alpaca_client=DummyAlpaca(),  # type: ignore[arg-type]
        polygon_client=FailingPolygonAgg(),  # type: ignore[arg-type]
        aggregator=DummyAggregator(),  # type: ignore[arg-type]
    )

    snapshot = collector.collect_market_snapshot(
        tickers=["AAPL"],
        lookback=timedelta(minutes=5),
        news_lookback=timedelta(minutes=5),
        timeframe="1Min",
        use_cache=False,
    )

    assert snapshot["AAPL"]["option_aggregates"] == {}


def test_market_data_collector_skips_underlying_bars_when_disabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_UNDERLYING_BARS", "0")
    settings = build_settings(monkeypatch)
    cache = LocalDataCache(root=tmp_path / "cache")
    alpaca = DummyAlpaca()
    collector = MarketDataCollector(
        settings,
        cache=cache,
        alpaca_client=alpaca,  # type: ignore[arg-type]
        polygon_client=DummyPolygon(),  # type: ignore[arg-type]
        aggregator=DummyAggregator(),  # type: ignore[arg-type]
    )

    snapshot = collector.collect_market_snapshot(
        tickers=["AAPL"],
        lookback=timedelta(minutes=5),
        news_lookback=timedelta(minutes=5),
        timeframe="1Min",
        use_cache=False,
    )

    assert alpaca.bar_calls == 0
    assert snapshot["AAPL"]["underlying_bars"].empty


def test_regular_session_open_utc_after_open() -> None:
    ts = datetime(2025, 11, 14, 15, 0, tzinfo=timezone.utc)
    open_ts = _regular_session_open_utc(ts)
    assert open_ts == datetime(2025, 11, 14, 14, 30, tzinfo=timezone.utc)


def test_regular_session_open_utc_before_open() -> None:
    ts = datetime(2025, 11, 14, 13, 0, tzinfo=timezone.utc)
    open_ts = _regular_session_open_utc(ts)
    assert open_ts == datetime(2025, 11, 13, 14, 30, tzinfo=timezone.utc)
