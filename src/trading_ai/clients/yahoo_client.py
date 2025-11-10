"""Yahoo Finance RSS headlines client."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

import feedparser
from loguru import logger

from trading_ai.clients.base import APIClientError, BaseClient


class YahooNewsClient(BaseClient):
    """Fetches ticker-specific RSS feeds from Yahoo Finance."""

    def __init__(self) -> None:
        super().__init__("yahoo_rss")

    def fetch_headlines(self, ticker: str, *, since: datetime | None = None, limit: int = 50) -> List[Dict[str, Any]]:
        feed_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as exc:  # pragma: no cover - network path
            logger.exception("Failed to fetch Yahoo RSS", ticker=ticker)
            raise APIClientError(f"Yahoo RSS error: {exc}") from exc

        entries = []
        for entry in parsed.entries[:limit]:
            published = entry.get("published_parsed")
            published_dt = datetime(*published[:6], tzinfo=timezone.utc) if published else None
            if since and published_dt and published_dt < since:
                continue
            entries.append(
                {
                    "title": entry.get("title"),
                    "description": entry.get("summary"),
                    "link": entry.get("link"),
                    "published_at": published_dt.isoformat() if published_dt else None,
                    "source": "yahoo",
                    "tickers": [ticker],
                }
            )
        self._log("Fetched Yahoo headlines", ticker=ticker, count=len(entries))
        return entries
