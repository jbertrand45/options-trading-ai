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
        self.quote_calls = 0

    def fetch_underlying_bars(self, **_: Any) -> DummyBars:
        self.bar_calls += 1
        frame = pd.DataFrame({"timestamp": [1, 2, 3], "close": [100.0, 101.0, 102.0]})
        return DummyBars(frame)

    def fetch_option_chain(self, **_: Any) -> List[Dict[str, Any]]:
        self.chain_calls += 1
        return [{"contract": "CALL", "strike": 100}]

    def fetch_option_latest_quote(self, **_: Any) -> Dict[str, Any]:
        self.quote_calls += 1
        return {"bid": 1.2, "ask": 1.3}


class DummyPolygon:
    def __init__(self) -> None:
        self.calls = 0
        self.bar_calls = 0

    def fetch_reference_news(self, **_: Any) -> Iterable[Dict[str, Any]]:
        self.calls += 1
        yield {"title": "Tech stock rallies", "source": "Polygon"}

    def fetch_equity_bars(self, **_: Any) -> Iterable[Dict[str, Any]]:
        self.bar_calls += 1
        return [{"timestamp": 1, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000}]


class DummyAggregator:
    def __init__(self) -> None:
        self.calls = 0
        self.providers = [lambda *args, **kwargs: None]

    def gather(self, ticker: str, since: datetime, limit: int = 50) -> List[Dict[str, Any]]:
        self.calls += 1
        return [{"title": "Breaking: New product", "source": "Aggregator"}]


def build_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("POLYGON_API_KEY", "polygon")
    monkeypatch.setenv("NEWS_API_KEY", "news")
    monkeypatch.setenv("NEWS_SECRET_KEY", "secret")
    monkeypatch.setenv("TARGET_TICKERS", '["AAPL"]')
    monkeypatch.setenv("USE_POLYGON_BARS", "1")
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
    assert alpaca.quote_calls == 0
    assert aggregator.calls == 1
    assert not result["AAPL"]["underlying_bars"].empty

    # Second call should reuse cached bars and option chain, but still hit latest quote.
    alpaca.quote_calls = 0  # reset (though never called now)
    result_second = collector.collect_market_snapshot(
        tickers=["AAPL"],
        lookback=timedelta(days=1),
        news_lookback=timedelta(hours=6),
        timeframe="1Min",
        use_cache=True,
    )

    assert alpaca.bar_calls == 0
    assert alpaca.chain_calls == 1
    assert alpaca.quote_calls == 0
    assert aggregator.calls == 1
    assert len(result_second["AAPL"]["news"]) == 1  # cached stories
