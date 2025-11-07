"""High-level orchestration that delegates to the market data collector."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Iterable, Optional

from trading_ai.core.collector import MarketDataCollector
from trading_ai.features import compute_intraday_features
from trading_ai.settings import Settings


class SignalPipeline:
    """Facade for downstream components to retrieve prepared market snapshots."""

    def __init__(self, settings: Settings, *, collector: Optional[MarketDataCollector] = None) -> None:
        self.settings = settings
        self.collector = collector or MarketDataCollector(settings)

    def collect_market_snapshot(
        self,
        tickers: Optional[Iterable[str]] = None,
        *,
        lookback: timedelta = timedelta(days=7),
        news_lookback: timedelta = timedelta(days=2),
        timeframe: str = "1Min",
        use_cache: bool = True,
        include_news: bool = True,
    ) -> Dict[str, Any]:
        """Collect underlying bars, option chains, quotes, and news for target tickers."""

        snapshot = self.collector.collect_market_snapshot(
            tickers=tickers,
            lookback=lookback,
            news_lookback=news_lookback,
            timeframe=timeframe,
            use_cache=use_cache,
            include_news=include_news,
        )
        for ticker, data in snapshot.items():
            data["features"] = compute_intraday_features(data["underlying_bars"])
        return snapshot
