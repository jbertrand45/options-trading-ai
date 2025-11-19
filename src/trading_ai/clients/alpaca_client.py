"""Adapter around Alpaca's trading and data APIs."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from alpaca.data.enums import DataFeed
from alpaca.data.historical import OptionHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import (
    OptionChainRequest,
    OptionLatestQuoteRequest,
    StockBarsRequest,
    StockLatestTradeRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest
from alpaca.trading.enums import OrderSide, TimeInForce, PositionIntent
from loguru import logger

from trading_ai.clients.base import APIClientError, BaseClient
from trading_ai.settings import Settings
from trading_ai.utils.dns import apply_dns_override


class AlpacaClient(BaseClient):
    """Lightweight wrapper around Alpaca clients."""

    def __init__(self, settings: Settings) -> None:
        mode = "paper" if settings.alpaca_paper_account else "live"
        super().__init__("alpaca", {"mode": mode})
        self._settings = settings
        self._data_feed = self._resolve_data_feed(settings.alpaca_data_feed)
        if settings.alpaca_data_override_ip:
            apply_dns_override("data.alpaca.markets", settings.alpaca_data_override_ip)
        verify_config: Any = True
        if settings.alpaca_ca_bundle:
            verify_config = settings.alpaca_ca_bundle
        elif not settings.alpaca_verify_tls:
            verify_config = False
            os.environ.setdefault("PYTHONHTTPSVERIFY", "0")
        self._trading_client = TradingClient(
            api_key=settings.alpaca_api_key_id,
            secret_key=settings.alpaca_api_secret_key,
            paper=settings.alpaca_paper_account,
        )
        self._option_client = OptionHistoricalDataClient(
            api_key=settings.alpaca_api_key_id,
            secret_key=settings.alpaca_api_secret_key,
        )
        self._equity_client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key_id,
            secret_key=settings.alpaca_api_secret_key,
        )
        self._configure_session_verify(verify_config)

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
            feed=self._data_feed,
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

    def submit_option_order(
        self,
        *,
        symbol: str,
        quantity: int,
        side: OrderSide,
        time_in_force: TimeInForce = TimeInForce.DAY,
        position_intent: PositionIntent = PositionIntent.BUY_TO_OPEN,
        take_profit_price: float | None = None,
        stop_loss_price: float | None = None,
    ) -> str:
        """Submit an options order via Alpaca's trading client."""

        order = MarketOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=side,
            time_in_force=time_in_force,
            position_intent=position_intent,
            take_profit=TakeProfitRequest(limit_price=take_profit_price) if take_profit_price else None,
            stop_loss=StopLossRequest(stop_price=stop_loss_price) if stop_loss_price else None,
        )
        try:
            response = self._trading_client.submit_order(order)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to submit option order", symbol=symbol, side=side)
            raise APIClientError(f"Alpaca option order error: {exc}") from exc
        self._log("Submitted option order", symbol=symbol, side=side.value, qty=quantity)
        return response.id

    def get_account_equity(self) -> float:
        """Return the latest account equity reported by Alpaca."""

        try:
            account = self._trading_client.get_account()
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch Alpaca account equity")
            raise APIClientError(f"Alpaca account equity error: {exc}") from exc
        equity = getattr(account, "equity", None)
        if equity is None:
            raise APIClientError("Alpaca account did not include equity field")
        try:
            return float(equity)
        except (TypeError, ValueError) as exc:
            raise APIClientError(f"Invalid equity value returned by Alpaca: {equity}") from exc

    def fetch_latest_trade(self, symbol: str) -> Any:
        """Fetch the most recent trade for a stock."""

        request = StockLatestTradeRequest(symbol_or_symbols=symbol)
        try:
            data = self._equity_client.get_stock_latest_trade(request)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch latest stock trade from Alpaca", symbol=symbol)
            raise APIClientError(f"Alpaca latest trade error: {exc}") from exc
        self._log("Fetched latest trade", symbol=symbol)
        return data

    def _configure_session_verify(self, verify: Any) -> None:
        for client in (self._option_client, self._equity_client, getattr(self, "_trading_client", None)):
            if not client:
                continue
            session = getattr(client, "_session", None)
            if session is not None:
                session.verify = verify

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

    def _resolve_data_feed(self, feed_name: str) -> DataFeed:
        normalized = (feed_name or "IEX").strip().upper()
        mapping = {
            "IEX": DataFeed.IEX,
            "SIP": DataFeed.SIP,
        }
        if normalized not in mapping:
            logger.warning("Unknown alpaca data feed '%s', defaulting to IEX", normalized)
        return mapping.get(normalized, DataFeed.IEX)
