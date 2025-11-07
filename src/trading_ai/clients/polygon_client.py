"""Polygon.io REST client adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

from loguru import logger
from polygon import RESTClient

from trading_ai.clients.base import APIClientError, BaseClient
from trading_ai.settings import Settings


class PolygonClient(BaseClient):
    """Wrapper around Polygon REST APIs used for options analytics."""

    def __init__(self, settings: Settings) -> None:
        super().__init__("polygon")
        self._client = RESTClient(api_key=settings.polygon_api_key)

    def fetch_option_aggregates(
        self,
        symbol: str,
        multiplier: int,
        timespan: str,
        start: datetime,
        end: datetime,
        limit: int = 5000,
    ) -> Iterable[Any]:
        """Stream aggregate bars for a specific option contract."""

        try:
            response = self._client.get_aggs(
                symbol=symbol,
                multiplier=multiplier,
                timespan=timespan,
                from_=start,
                to=end,
                limit=limit,
            )
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch Polygon aggregates", symbol=symbol)
            raise APIClientError(f"Polygon aggregate error: {exc}") from exc
        self._log("Fetched Polygon aggregates", symbol=symbol, count=len(response))
        return response

    def fetch_reference_news(
        self,
        ticker: str,
        published_gte: Optional[datetime] = None,
        limit: int = 50,
    ) -> Iterable[Any]:
        """Fetch recent news articles for a ticker."""

        try:
            response = self._client.list_ticker_news(
                ticker=ticker,
                published_utc=published_gte,
                limit=limit,
            )
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch Polygon news", ticker=ticker)
            raise APIClientError(f"Polygon news error: {exc}") from exc
        self._log("Fetched Polygon news", ticker=ticker)
        return response

    def fetch_equity_bars(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        timeframe: str = "minute",
        limit: int = 5000,
    ) -> Iterable[Any]:
        """Fetch equity bars for underlying via Polygon."""

        try:
            response = list(
                self._client.list_aggs(
                    ticker=ticker,
                    multiplier=1,
                    timespan=timeframe,
                    from_=start,
                    to=end,
                    limit=limit,
                    adjusted=True,
                )
            )
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to fetch Polygon equity bars", ticker=ticker)
            raise APIClientError(f"Polygon equity bars error: {exc}") from exc
        payload = []
        for bar in response:
            if hasattr(bar, "model_dump"):
                payload.append(bar.model_dump())
            elif hasattr(bar, "__dict__"):
                payload.append(bar.__dict__)
            else:
                payload.append(bar)
        self._log("Fetched Polygon equity bars", ticker=ticker)
        return payload
