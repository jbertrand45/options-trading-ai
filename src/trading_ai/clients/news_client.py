"""News sentiment ingestion."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable

import requests
from loguru import logger

from trading_ai.clients.base import APIClientError, BaseClient
from trading_ai.settings import Settings


class NewsClient(BaseClient):
    """Simple REST client for generic news APIs (e.g., NewsAPI.org)."""

    def __init__(self, settings: Settings) -> None:
        super().__init__("news")
        self._api_key = settings.news_api_key
        if not self._api_key:
            logger.warning("News API key is not configured; news ingestion will be disabled.")

    def fetch_headlines(self, ticker: str, from_date: datetime | None = None, limit: int = 50) -> Iterable[Dict[str, Any]]:
        """Fetch recent headlines related to a ticker."""

        if not self._api_key:
            raise APIClientError("News API key not configured")

        params: Dict[str, Any] = {
            "q": ticker,
            "pageSize": limit,
            "sortBy": "publishedAt",
            "apiKey": self._api_key,
            "language": "en",
        }
        if from_date:
            params["from"] = from_date.isoformat()

        try:
            response = requests.get("https://newsapi.org/v2/everything", params=params, timeout=10)
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch news headlines", ticker=ticker)
            raise APIClientError(f"News API error: {exc}") from exc

        data = response.json()
        articles = data.get("articles", [])
        self._log("Fetched news headlines", ticker=ticker, count=len(articles))
        return articles
