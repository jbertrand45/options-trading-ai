"""Polygon.io REST client adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

from urllib.parse import urlparse

from loguru import logger
from polygon import RESTClient

from trading_ai.clients.base import APIClientError, BaseClient
from trading_ai.settings import Settings
from trading_ai.utils.dns import apply_dns_override


class PolygonClient(BaseClient):
    """Wrapper around Polygon REST APIs used for options analytics."""

    def __init__(self, settings: Settings) -> None:
        super().__init__("polygon")
        if settings.polygon_api_override_ip:
            override_host = urlparse(settings.polygon_base_url).netloc or "api.polygon.io"
            apply_dns_override(override_host, settings.polygon_api_override_ip)
        self._client = RESTClient(api_key=settings.polygon_api_key, base=settings.polygon_base_url)

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
                ticker=symbol,
                multiplier=multiplier,
                timespan=timespan,
                from_=start,
                to=end,
                limit=limit,
            )
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch Polygon aggregates", symbol=symbol)
            raise APIClientError(f"Polygon aggregate error: {exc}") from exc
        payload = []
        for agg in response:
            if hasattr(agg, "model_dump"):
                payload.append(agg.model_dump())
            elif hasattr(agg, "__dict__"):
                payload.append(agg.__dict__)
            else:
                payload.append(agg)
        self._log("Fetched Polygon aggregates", symbol=symbol, count=len(payload))
        return payload

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

    def fetch_option_contracts(
        self,
        underlying: str,
        *,
        limit: int = 300,
        as_of: Optional[datetime] = None,
    ) -> Iterable[Any]:
        """Fetch option contract references with greeks/open interest."""

        try:
            response = list(
                self._client.list_options_contracts(
                    underlying_ticker=underlying,
                    limit=limit,
                    as_of=as_of.date() if as_of else None,
                )
            )
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch Polygon option contracts", ticker=underlying)
            raise APIClientError(f"Polygon option contracts error: {exc}") from exc
        self._log("Fetched Polygon option contracts", ticker=underlying, count=len(response))
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
