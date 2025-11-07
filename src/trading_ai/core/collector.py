"""Market data ingestion utilities with caching support."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
from loguru import logger

from trading_ai.clients import (
    AlpacaClient,
    AlphaVantageNewsClient,
    MarketauxClient,
    NewsAggregator,
    NewsClient,
    PolygonClient,
    YahooNewsClient,
)
from trading_ai.clients.base import APIClientError
from trading_ai.data.cache import LocalDataCache
from trading_ai.settings import Settings


class MarketDataCollector:
    """Coordinates incremental data pulls across providers with local caching."""

    def __init__(
        self,
        settings: Settings,
        *,
        cache: Optional[LocalDataCache] = None,
        alpaca_client: Optional[AlpacaClient] = None,
        polygon_client: Optional[PolygonClient] = None,
        news_client: Optional[NewsClient] = None,
        aggregator: Optional[NewsAggregator] = None,
    ) -> None:
        self.settings = settings
        self.cache = cache or LocalDataCache()
        self.alpaca = alpaca_client or AlpacaClient(settings)
        self.polygon = polygon_client or PolygonClient(settings)
        self.enable_news = settings.enable_news
        self.use_polygon_bars = settings.use_polygon_bars

        base_news_client = news_client or (NewsClient(settings) if settings.news_api_key else None)
        yahoo_client = YahooNewsClient()
        alpha_client = (
            AlphaVantageNewsClient(settings.alpha_vantage_api_key)
            if settings.alpha_vantage_api_key
            else None
        )
        marketaux_client = (
            MarketauxClient(settings.marketaux_api_key)
            if settings.marketaux_api_key
            else None
        )
        self.aggregator = aggregator or NewsAggregator(
            polygon_client=self.polygon,
            news_api_client=base_news_client,
            yahoo_client=yahoo_client,
            alpha_client=alpha_client,
            marketaux_client=marketaux_client,
        )

    # --------------------------------------------------------------------- helpers

    def _frame_from_payload(self, payload: Any) -> pd.DataFrame:
        if payload is None:
            return pd.DataFrame()
        if isinstance(payload, pd.DataFrame):
            return payload.copy()
        if hasattr(payload, "df"):
            frame = getattr(payload, "df")
            if hasattr(frame, "reset_index"):
                frame = frame.reset_index()
            return pd.DataFrame(frame)
        if isinstance(payload, list):
            return pd.DataFrame(payload)
        if isinstance(payload, dict):
            return pd.DataFrame([payload])
        return pd.DataFrame()

    def _serialize_payload(self, payload: Any) -> Any:
        if payload is None:
            return None
        if isinstance(payload, (str, int, float, bool)):
            return payload
        if isinstance(payload, list):
            return [self._serialize_payload(item) for item in payload]
        if isinstance(payload, dict):
            return {key: self._serialize_payload(value) for key, value in payload.items()}
        if hasattr(payload, "model_dump"):
            return payload.model_dump()
        if hasattr(payload, "to_dict"):
            return payload.to_dict()
        if hasattr(payload, "__dict__"):
            return self._serialize_payload(payload.__dict__)
        return str(payload)

    # ------------------------------------------------------------------- collectors

    def collect_underlying_bars(
        self,
        ticker: str,
        *,
        start: datetime,
        end: datetime,
        timeframe: str = "1Min",
        use_cache: bool = True,
    ) -> pd.DataFrame:
        duration_key = f"{int((end - start).total_seconds())}s"
        end_bucket = end.strftime("%Y%m%d")
        cache_key = ("alpaca", "bars", ticker, timeframe, duration_key, end_bucket)
        if use_cache and self.cache.exists(*cache_key):
            return self.cache.read_dataframe(*cache_key)

        frame = pd.DataFrame()
        if self.use_polygon_bars:
            try:
                frame = self._frame_from_payload(
                    self.polygon.fetch_equity_bars(
                        ticker=ticker,
                        start=start,
                        end=end,
                        timeframe=_polygon_timespan(timeframe),
                    )
                )
            except APIClientError:
                logger.warning("Polygon equity bars unavailable; falling back to Alpaca", ticker=ticker)

        if frame.empty:
            try:
                alpaca_bars = self.alpaca.fetch_underlying_bars(symbol=ticker, start=start, end=end, timeframe=timeframe)
                frame = self._frame_from_payload(alpaca_bars)
            except APIClientError:
                logger.warning("Alpaca equity bars unavailable", ticker=ticker)
                frame = pd.DataFrame()
        if not frame.empty:
            try:
                self.cache.write_dataframe(frame, *cache_key)
            except ValueError:
                logger.debug("Skipping cache write for empty frame", ticker=ticker)
        return frame

    def collect_option_chain(
        self,
        ticker: str,
        *,
        expiration: Optional[datetime] = None,
        use_cache: bool = True,
    ) -> Any:
        cache_key = ("alpaca", "option-chain", ticker, expiration.isoformat() if expiration else "any")
        if use_cache and self.cache.exists(*cache_key, suffix=".json"):
            return self.cache.read_json(*cache_key)

        chain = self.alpaca.fetch_option_chain(symbol=ticker, expiration=expiration)
        serialized = self._serialize_payload(chain)
        if serialized is not None:
            self.cache.write_json(serialized, *cache_key)
        return serialized

    def collect_option_quote(self, ticker: str, *, use_cache: bool = False) -> Any:
        cache_key = ("alpaca", "option-quote", ticker)
        if use_cache and self.cache.exists(*cache_key, suffix=".json"):
            return self.cache.read_json(*cache_key)

        logger.debug("Skipping option quote fetch; contract symbols required", ticker=ticker)
        return {}

    def collect_news(
        self,
        ticker: str,
        *,
        since: datetime,
        limit: int = 50,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        if not self.enable_news or not self.aggregator.providers:
            return []

        cache_key = ("news", ticker, since.date().isoformat(), str(limit))
        if use_cache and self.cache.exists(*cache_key, suffix=".json"):
            cached = self.cache.read_json(*cache_key)
            return list(cached)

        stories = self.aggregator.gather(ticker, since=since, limit=limit)
        if stories:
            self.cache.write_json(stories, *cache_key)
        return stories

    # ------------------------------------------------------------------- orchestration

    def collect_market_snapshot(
        self,
        *,
        tickers: Optional[Iterable[str]] = None,
        lookback: timedelta = timedelta(days=7),
        news_lookback: timedelta = timedelta(days=2),
        timeframe: str = "1Min",
        use_cache: bool = True,
        include_news: bool = True,
    ) -> Dict[str, Dict[str, Any]]:
        now = datetime.utcnow()
        bar_start = now - lookback
        news_since = now - news_lookback
        snapshot: Dict[str, Dict[str, Any]] = {}
        ticker_list = list(tickers or self.settings.target_tickers)

        for ticker in ticker_list:
            logger.info("Collecting market snapshot", ticker=ticker)
            bars = self.collect_underlying_bars(
                ticker,
                start=bar_start,
                end=now,
                timeframe=timeframe,
                use_cache=use_cache,
            )
            option_chain = self.collect_option_chain(ticker, use_cache=use_cache)
            option_quote = self.collect_option_quote(ticker, use_cache=False)
            news_items: List[Dict[str, Any]] = []
            if include_news:
                news_items = self.collect_news(ticker, since=news_since, use_cache=use_cache)

            snapshot[ticker] = {
                "collected_at": now.isoformat(),
                "underlying_bars": bars,
                "option_chain": option_chain,
                "option_quote": option_quote,
                "news": news_items,
            }
        return snapshot


def _polygon_timespan(timeframe: str) -> str:
    mapping = {
        "1Min": "minute",
        "5Min": "minute",
        "15Min": "minute",
        "1Hour": "hour",
        "1Day": "day",
    }
    return mapping.get(timeframe, "minute")
