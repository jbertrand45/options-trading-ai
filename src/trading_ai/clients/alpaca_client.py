"""Adapter around Alpaca's trading and data APIs."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

from alpaca.data.enums import DataFeed
from alpaca.data.historical import OptionHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import (
    OptionChainRequest,
    OptionSnapshotRequest,
    OptionBarsRequest,
    OptionLatestQuoteRequest,
    StockBarsRequest,
    StockLatestTradeRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, OrderSide, TimeInForce, PositionIntent
from alpaca.trading.requests import (
    GetAssetsRequest,
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)
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
        oauth_token = settings.alpaca_oauth_token
        if oauth_token:
            trading_kwargs = {"oauth_access_token": oauth_token, "paper": settings.alpaca_paper_account}
            data_kwargs = {"oauth_token": oauth_token}
        else:
            trading_kwargs = {
                "api_key": settings.alpaca_api_key_id,
                "secret_key": settings.alpaca_api_secret_key,
                "paper": settings.alpaca_paper_account,
            }
            data_kwargs = {
                "api_key": settings.alpaca_api_key_id,
                "secret_key": settings.alpaca_api_secret_key,
            }

        self._trading_client = TradingClient(**trading_kwargs)
        self._option_client = OptionHistoricalDataClient(**data_kwargs)
        self._equity_client = StockHistoricalDataClient(**data_kwargs)
        self._configure_session_verify(verify_config)

    def fetch_option_chain(self, symbol: str, expiration: Optional[datetime] = None) -> Any:
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

    def fetch_option_snapshot(self, symbols: str | list[str]) -> Any:
        """Fetch option snapshot(s) for one or more OCC symbols."""

        request = OptionSnapshotRequest(symbol_or_symbols=symbols)
        try:
            data = self._option_client.get_option_snapshot(request)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch option snapshot(s) from Alpaca", symbols=symbols)
            raise APIClientError(f"Alpaca option snapshot error: {exc}") from exc
        self._log("Fetched option snapshot", symbols=symbols)
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

    def fetch_option_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1Min",
        limit: int = 5000,
    ) -> Any:
        """Fetch historical option bars for a specific contract."""

        bar_timeframe = self._parse_timeframe(timeframe)
        request = OptionBarsRequest(
            symbol_or_symbols=symbol,
            start=start,
            end=end,
            timeframe=bar_timeframe,
            limit=limit,
        )
        try:
            bars = self._option_client.get_option_bars(request)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch option bars from Alpaca", symbol=symbol)
            raise APIClientError(f"Alpaca option bars error: {exc}") from exc
        self._log("Fetched option bars", symbol=symbol, feed="alpaca")
        return bars

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
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        limit_price: Optional[float] = None,
    ) -> str:
        """Submit an options order via Alpaca's trading client."""

        # Round prices to 2 decimal places (Alpaca requirement)
        if limit_price is not None:
            limit_price = round(limit_price, 2)
        if take_profit_price is not None:
            take_profit_price = round(take_profit_price, 2)
        if stop_loss_price is not None:
            stop_loss_price = round(stop_loss_price, 2)

        if limit_price is not None:
            order = LimitOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=side,
                time_in_force=time_in_force,
                limit_price=limit_price,
                position_intent=position_intent,
                take_profit=TakeProfitRequest(limit_price=take_profit_price) if take_profit_price else None,
                stop_loss=StopLossRequest(stop_price=stop_loss_price) if stop_loss_price else None,
            )
        else:
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

    def fetch_account(self) -> Any:
        """Return the full trading account payload (includes options levels)."""

        try:
            return self._trading_client.get_account()
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch Alpaca account")
            raise APIClientError(f"Alpaca account fetch error: {exc}") from exc

    def check_options_trading_enabled(self) -> bool:
        """Verify the account has options trading approval from Alpaca."""

        try:
            account = self.fetch_account()
            # Check for options_trading_level or options_approved_level attributes
            options_level = getattr(account, "options_trading_level", None) or getattr(
                account, "options_approved_level", None
            )
            if options_level is None:
                # If no explicit level, check if options_buying_power exists and is > 0
                options_bp = getattr(account, "options_buying_power", None)
                if options_bp is not None:
                    try:
                        return float(options_bp) > 0
                    except (TypeError, ValueError):
                        pass
                logger.warning(
                    "Could not determine options trading level from account - proceed with caution"
                )
                return True  # Assume enabled if can't determine (fail open for compatibility)
            # Level 0 = not approved, Level 1+ = approved for various strategies
            try:
                level_int = int(options_level)
                return level_int >= 1
            except (TypeError, ValueError):
                logger.warning(f"Invalid options trading level format: {options_level}")
                return True  # Fail open
        except APIClientError:
            logger.warning("Could not verify options trading level - proceeding with caution")
            return True  # Fail open if account fetch fails

    def get_options_buying_power(self) -> float:
        """Return options buying power if available, otherwise fall back to buying power or equity."""

        try:
            account = self._trading_client.get_account()
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch Alpaca account")
            raise APIClientError(f"Alpaca account fetch error: {exc}") from exc
        for field in ("options_buying_power", "buying_power", "regt_buying_power", "equity"):
            value = getattr(account, field, None)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        raise APIClientError("Alpaca account did not include usable buying power")

    def get_position_qty(self, symbol: str) -> int:
        """Return current open share quantity for an underlying."""

        try:
            pos = self._trading_client.get_open_position(symbol)
        except Exception:
            return 0
        qty = getattr(pos, "qty", None) or getattr(pos, "qty_available", None)
        try:
            return int(float(qty))
        except (TypeError, ValueError):
            return 0

    def list_positions(self) -> Any:
        """Return all open positions (equity + options)."""

        try:
            return self._trading_client.get_all_positions()
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch Alpaca positions")
            raise APIClientError(f"Alpaca positions error: {exc}") from exc

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

    def list_assets(self, status: str = "active", asset_class: str = "us_equity") -> Any:
        """List tradable assets; filter for options-enabled underlyings if needed."""

        try:
            asset_class_enum = AssetClass(asset_class) if asset_class else None
        except Exception:
            asset_class_enum = None
        req = GetAssetsRequest(status=status, asset_class=asset_class_enum or asset_class)
        try:
            assets = self._trading_client.get_all_assets(req)
        except Exception as exc:  # pragma: no cover - dependency failure path
            logger.exception("Failed to list assets from Alpaca", status=status, asset_class=asset_class)
            raise APIClientError(f"Alpaca assets error: {exc}") from exc
        self._log("Fetched assets", status=status, asset_class=asset_class)
        return assets

    def list_orders(self, status: Optional[str] = None) -> Any:
        """List orders with optional status filter ('open', 'closed', 'all')."""

        req = GetOrdersRequest(status=status)
        try:
            orders = self._trading_client.get_orders(req)
        except Exception as exc:  # pragma: no cover - dependency failure path
            logger.exception("Failed to list orders from Alpaca", status=status)
            raise APIClientError(f"Alpaca orders error: {exc}") from exc
        self._log("Fetched orders", status=status or "all")
        return orders

    def get_order(self, order_id: str) -> Any:
        """Fetch a single order by ID."""

        try:
            return self._trading_client.get_order_by_id(order_id)
        except Exception as exc:  # pragma: no cover - dependency failure path
            logger.exception("Failed to fetch order from Alpaca", order_id=order_id)
            raise APIClientError(f"Alpaca order error: {exc}") from exc

    def cancel_order(self, order_id: str) -> None:
        """Cancel an open order."""

        try:
            self._trading_client.cancel_order_by_id(order_id)
        except Exception as exc:  # pragma: no cover - dependency failure path
            logger.exception("Failed to cancel order via Alpaca", order_id=order_id)
            raise APIClientError(f"Alpaca cancel order error: {exc}") from exc

    def option_is_tradable(self, symbol: str) -> bool:
        """Return True if Alpaca returns a tradable snapshot for the option symbol."""

        try:
            req = OptionSnapshotRequest(symbol_or_symbols=symbol)
            snap = self._option_client.get_option_snapshot(req)
        except Exception:
            return False
        if hasattr(snap, "latest_quote"):
            quote = snap.latest_quote
            bid = getattr(quote, "bid_price", None) or getattr(quote, "bid", None)
            ask = getattr(quote, "ask_price", None) or getattr(quote, "ask", None)
            try:
                bid_f = float(bid) if bid is not None else 0.0
                ask_f = float(ask) if ask is not None else 0.0
            except (TypeError, ValueError):
                bid_f = ask_f = 0.0
            return bid_f > 0 or ask_f > 0
        return False

    def get_open_positions(self):
        """Return all open positions."""

        try:
            return self._trading_client.get_all_positions()
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to fetch open positions from Alpaca")
            raise APIClientError(f"Alpaca positions error: {exc}") from exc

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
