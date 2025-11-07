"""Aggregates news across Polygon, Yahoo, Alpha Vantage, Marketaux, and NewsAPI."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

from loguru import logger

from trading_ai.clients.alpha_vantage_client import AlphaVantageNewsClient
from trading_ai.clients.base import APIClientError
from trading_ai.clients.marketaux_client import MarketauxClient
from trading_ai.clients.news_client import NewsClient
from trading_ai.clients.polygon_client import PolygonClient
from trading_ai.clients.yahoo_client import YahooNewsClient

ProviderFn = Callable[[str, datetime | None, int], List[Dict[str, Any]]]


class NewsAggregator:
    """Combines multiple news providers and handles graceful degradation."""

    def __init__(
        self,
        *,
        polygon_client: Optional[PolygonClient] = None,
        news_api_client: Optional[NewsClient] = None,
        yahoo_client: Optional[YahooNewsClient] = None,
        alpha_client: Optional[AlphaVantageNewsClient] = None,
        marketaux_client: Optional[MarketauxClient] = None,
    ) -> None:
        self.providers: List[ProviderFn] = []
        if polygon_client:
            self.providers.append(lambda ticker, since, limit: list(polygon_client.fetch_reference_news(ticker=ticker, published_gte=since, limit=limit)))
        if yahoo_client:
            self.providers.append(lambda ticker, since, limit: yahoo_client.fetch_headlines(ticker=ticker, since=since, limit=limit))
        if alpha_client:
            self.providers.append(lambda ticker, since, limit: alpha_client.fetch_headlines(ticker=ticker, since=since, limit=limit))
        if marketaux_client:
            self.providers.append(lambda ticker, since, limit: marketaux_client.fetch_headlines(ticker=ticker, since=since, limit=limit))
        if news_api_client:
            self.providers.append(lambda ticker, since, limit: news_api_client.fetch_headlines(ticker=ticker, from_date=since, limit=limit))

    def gather(self, ticker: str, *, since: datetime, limit: int = 50) -> List[Dict[str, Any]]:
        seen = set()
        combined: List[Dict[str, Any]] = []
        for provider in self.providers:
            try:
                articles = provider(ticker, since, limit)
            except APIClientError:
                logger.warning("News provider failed", ticker=ticker, provider=provider.__qualname__)
                continue
            except Exception:
                logger.debug("News provider disabled or misconfigured", ticker=ticker, provider=provider.__qualname__)
                continue
            for article in articles:
                title = (article.get("title") or "").strip()
                key = (title, article.get("link"))
                if title and key not in seen:
                    combined.append(article)
                    seen.add(key)
            if len(combined) >= limit:
                break
        return combined[:limit]
