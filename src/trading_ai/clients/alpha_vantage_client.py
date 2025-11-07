"""Alpha Vantage news/sentiment client."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

import requests
from loguru import logger

from trading_ai.clients.base import APIClientError, BaseClient


class AlphaVantageNewsClient(BaseClient):
    """Fetches news & sentiment data from Alpha Vantage."""

    def __init__(self, api_key: str) -> None:
        super().__init__("alpha_vantage")
        self._api_key = api_key

    def fetch_headlines(self, ticker: str, *, since: datetime | None = None, limit: int = 50) -> List[Dict[str, Any]]:
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": ticker,
            "apikey": self._api_key,
            "limit": str(limit),
        }
        if since:
            params["time_from"] = since.strftime("%Y%m%dT%H%M")
        try:
            response = requests.get("https://www.alphavantage.co/query", params=params, timeout=10)
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - network path
            logger.exception("Alpha Vantage news fetch failed", ticker=ticker)
            raise APIClientError(f"Alpha Vantage error: {exc}") from exc

        data = response.json()
        items = data.get("feed", [])
        normalized: List[Dict[str, Any]] = []
        for item in items:
            published = item.get("time_published")
            normalized.append(
                {
                    "title": item.get("title"),
                    "description": item.get("summary"),
                    "link": item.get("url"),
                    "published_at": published,
                    "sentiment": item.get("overall_sentiment_score"),
                    "source": "alpha_vantage",
                    "tickers": item.get("ticker_sentiment", []),
                }
            )
        self._log("Fetched Alpha Vantage news", ticker=ticker, count=len(normalized))
        return normalized
