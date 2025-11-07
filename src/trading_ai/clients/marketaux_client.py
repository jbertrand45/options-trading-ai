"""Marketaux news API client."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

import requests
from loguru import logger

from trading_ai.clients.base import APIClientError, BaseClient


class MarketauxClient(BaseClient):
    """Fetches curated news from the Marketaux API."""

    def __init__(self, api_token: str) -> None:
        super().__init__("marketaux")
        self._token = api_token

    def fetch_headlines(self, ticker: str, *, since: datetime | None = None, limit: int = 50) -> List[Dict[str, Any]]:
        params = {
            "symbols": ticker,
            "api_token": self._token,
            "language": "en",
            "limit": limit,
            "filter_entities": "true",
        }
        if since:
            params["published_after"] = since.isoformat()
        try:
            response = requests.get("https://api.marketaux.com/v1/news/all", params=params, timeout=10)
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover
            logger.exception("Marketaux news fetch failed", ticker=ticker)
            raise APIClientError(f"Marketaux error: {exc}") from exc

        data = response.json()
        articles = data.get("data", [])
        normalized: List[Dict[str, Any]] = []
        for article in articles:
            normalized.append(
                {
                    "title": article.get("title"),
                    "description": article.get("description"),
                    "link": article.get("url"),
                    "published_at": article.get("published_at"),
                    "source": "marketaux",
                    "sentiment": article.get("sentiment"),
                    "tickers": [t.get("symbol") for t in article.get("entities", []) if t.get("type") == "equity"],
                }
            )
        self._log("Fetched Marketaux news", ticker=ticker, count=len(normalized))
        return normalized
