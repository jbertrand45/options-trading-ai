"""Adapter around Alpaca's trading and data APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from alpaca.data.enums import DataFeed
from alpaca.data.historical import OptionHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import OptionChainRequest, OptionLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from loguru import logger

from trading_ai.clients.base import APIClientError, BaseClient
from trading_ai.settings import Settings


class AlpacaClient(BaseClient):
    """Lightweight wrapper around Alpaca clients."""

    def __init__(self, settings: Settings) -> None:
        super().__init__("alpaca", {"mode": "paper"})
        self._settings = settings
        self._trading_client = TradingClient(
            api_key=settings.alpaca_api_key_id,
            secret_key=settings.alpaca_api_secret_key,
            paper=True,
        )
        self._option_client = OptionHistoricalDataClient(
            api_key=settings.alpaca_api_key_id,
            secret_key=settings.alpaca_api_secret_key,
        )
        self._equity_client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key_id,
            secret_key=settings.alpaca_api_secret_key,
        )

    def fetch_option_chain(self, symbol: str, expiration: datetime | None = None) -> Any:
        """
        Fetch option chain snapshot for a given underlying symbol.

        Returns raw response from Alpaca's OptionHistoricalDataClient for now.
        """

        request = OptionChainRequest(underlying_symbol=symbol, expiration_date=expiration)
        try:
            data = self._option_client.get_option_chain(request)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch option chain from Alpaca", symbol=symbol)
            raise APIClientError(f"Alpaca option chain error: {exc}") from exc
        self._log("Fetched option chain", symbol=symbol)
        return data

    def fetch_option_latest_quote(self, symbol: str) -> Any:
        """Fetch the latest option quote for a symbol."""

        request = OptionLatestQuoteRequest(symbol_or_symbols=symbol)
        try:
            data = self._option_client.get_option_latest_quote(request)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch option quotes from Alpaca", symbol=symbol)
            raise APIClientError(f"Alpaca option quotes error: {exc}") from exc
        self._log("Fetched latest option quote", symbol=symbol)
        return data

    def fetch_underlying_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1Min",
    ) -> Any:
        """Fetch underlying equity bars for feature generation."""

        bar_timeframe = self._parse_timeframe(timeframe)

        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            start=start,
            end=end,
            timeframe=bar_timeframe,
            feed=DataFeed.IEX,
        )
        try:
            bars = self._equity_client.get_stock_bars(request)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch stock bars from Alpaca", symbol=symbol)
            raise APIClientError(f"Alpaca stock bars error: {exc}") from exc
        self._log("Fetched equity bars", symbol=symbol, feed="alpaca")
        return bars

    def submit_market_order(
        self,
        symbol: str,
        quantity: int,
        side: OrderSide,
        time_in_force: TimeInForce = TimeInForce.DAY,
    ) -> str:
        """Submit a market order via Alpaca trading client."""

        order = MarketOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=side,
            time_in_force=time_in_force,
        )
        try:
            response = self._trading_client.submit_order(order)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to submit order via Alpaca", symbol=symbol, side=side)
            raise APIClientError(f"Alpaca order submission error: {exc}") from exc
        self._log("Submitted market order", symbol=symbol, side=side.value, qty=quantity)
        return response.id

    def _parse_timeframe(self, value: str | TimeFrame) -> TimeFrame:
        if isinstance(value, TimeFrame):
            return value
        raw = str(value).strip().lower()
        units = [
            ("min", TimeFrameUnit.Minute),
            ("minute", TimeFrameUnit.Minute),
            ("hour", TimeFrameUnit.Hour),
            ("day", TimeFrameUnit.Day),
            ("week", TimeFrameUnit.Week),
            ("month", TimeFrameUnit.Month),
        ]
        for suffix, unit in units:
            if raw.endswith(suffix):
                amount_part = raw[: -len(suffix)].strip()
                if not amount_part:
                    amount = 1
                else:
                    amount = int(amount_part)
                return TimeFrame(amount, unit)
        raise ValueError(f"Unsupported timeframe: {value}")
