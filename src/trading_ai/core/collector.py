"""Market data ingestion utilities with caching support."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
from loguru import logger

from trading_ai.clients import (
    AlpacaClient,
    AlphaVantageNewsClient,
    MarketauxClient,
    NewsAggregator,
    NewsClient,
    PolygonClient,
    YahooNewsClient,
)
from trading_ai.clients.base import APIClientError
from trading_ai.data.cache import LocalDataCache
from trading_ai.settings import Settings


class MarketDataCollector:
    """Coordinates incremental data pulls across providers with local caching."""

    def __init__(
        self,
        settings: Settings,
        *,
        cache: Optional[LocalDataCache] = None,
        alpaca_client: Optional[AlpacaClient] = None,
        polygon_client: Optional[PolygonClient] = None,
        news_client: Optional[NewsClient] = None,
        aggregator: Optional[NewsAggregator] = None,
    ) -> None:
        self.settings = settings
        self.cache = cache or LocalDataCache()
        self.alpaca = alpaca_client or AlpacaClient(settings)
        self.polygon = polygon_client or PolygonClient(settings)
        self.enable_news = settings.enable_news
        self.use_polygon_bars = settings.use_polygon_bars

        base_news_client = news_client or (NewsClient(settings) if settings.news_api_key else None)
        yahoo_client = YahooNewsClient()
        alpha_client = (
            AlphaVantageNewsClient(settings.alpha_vantage_api_key)
            if settings.alpha_vantage_api_key
            else None
        )
        marketaux_client = (
            MarketauxClient(settings.marketaux_api_key)
            if settings.marketaux_api_key
            else None
        )
        self.aggregator = aggregator or NewsAggregator(
            polygon_client=self.polygon,
            news_api_client=base_news_client,
            yahoo_client=yahoo_client,
            alpha_client=alpha_client,
            marketaux_client=marketaux_client,
        )

    # --------------------------------------------------------------------- helpers

    def _frame_from_payload(self, payload: Any) -> pd.DataFrame:
        if payload is None:
            return pd.DataFrame()
        if isinstance(payload, pd.DataFrame):
            return payload.copy()
        if hasattr(payload, "df"):
            frame = getattr(payload, "df")
            if hasattr(frame, "reset_index"):
                frame = frame.reset_index()
            return pd.DataFrame(frame)
        if isinstance(payload, list):
            return pd.DataFrame(payload)
        if isinstance(payload, dict):
            return pd.DataFrame([payload])
        return pd.DataFrame()

    def _serialize_payload(self, payload: Any) -> Any:
        if payload is None:
            return None
        if isinstance(payload, (str, int, float, bool)):
            return payload
        if isinstance(payload, list):
            return [self._serialize_payload(item) for item in payload]
        if isinstance(payload, dict):
            return {key: self._serialize_payload(value) for key, value in payload.items()}
        if hasattr(payload, "model_dump"):
            return payload.model_dump()
        if hasattr(payload, "to_dict"):
            return payload.to_dict()
        if hasattr(payload, "__dict__"):
            return self._serialize_payload(payload.__dict__)
        return str(payload)

    # ------------------------------------------------------------------- collectors

    def collect_underlying_bars(
        self,
        ticker: str,
        *,
        start: datetime,
        end: datetime,
        timeframe: str = "1Min",
        use_cache: bool = True,
    ) -> pd.DataFrame:
        duration_key = f"{int((end - start).total_seconds())}s"
        end_bucket = end.strftime("%Y%m%d")
        cache_key = ("alpaca", "bars", ticker, timeframe, duration_key, end_bucket)
        if use_cache and self.cache.exists(*cache_key):
            return self.cache.read_dataframe(*cache_key)

        frame = pd.DataFrame()
        if self.use_polygon_bars:
            try:
                frame = self._frame_from_payload(
                    self.polygon.fetch_equity_bars(
                        ticker=ticker,
                        start=start,
                        end=end,
                        timeframe=_polygon_timespan(timeframe),
                    )
                )
            except APIClientError:
                logger.warning("Polygon equity bars unavailable; falling back to Alpaca", ticker=ticker)

        if frame.empty:
            try:
                alpaca_bars = self.alpaca.fetch_underlying_bars(symbol=ticker, start=start, end=end, timeframe=timeframe)
                frame = self._frame_from_payload(alpaca_bars)
            except APIClientError:
                logger.warning("Alpaca equity bars unavailable", ticker=ticker)
                frame = pd.DataFrame()
        if frame.empty and not self.use_polygon_bars:
            try:
                frame = self._frame_from_payload(
                    self.polygon.fetch_equity_bars(
                        ticker=ticker,
                        start=start,
                        end=end,
                        timeframe=_polygon_timespan(timeframe),
                    )
                )
                logger.info("Polygon fallback delivered equity bars", ticker=ticker)
            except APIClientError:
                logger.warning("Polygon fallback failed", ticker=ticker)
        if frame.empty:
            frame = self._frame_from_latest_trade(ticker)
        if not frame.empty:
            try:
                self.cache.write_dataframe(frame, *cache_key)
            except ValueError:
                logger.debug("Skipping cache write for empty frame", ticker=ticker)
        return frame

    def collect_option_chain(
        self,
        ticker: str,
        *,
        expiration: Optional[datetime] = None,
        use_cache: bool = True,
    ) -> Any:
        cache_key = ("alpaca", "option-chain", ticker, expiration.isoformat() if expiration else "any")
        if use_cache and self.cache.exists(*cache_key, suffix=".json"):
            return self.cache.read_json(*cache_key)

        chain = self.alpaca.fetch_option_chain(symbol=ticker, expiration=expiration)
        serialized = self._serialize_payload(chain)
        if serialized is not None:
            self.cache.write_json(serialized, *cache_key)
        return serialized

    def collect_option_quote(
        self,
        ticker: str,
        *,
        option_chain: Any | None = None,
        bars: pd.DataFrame | None = None,
        use_cache: bool = False,
    ) -> Dict[str, Any]:
        """Derive representative call/put quotes from the option chain payload."""

        if option_chain is None:
            logger.debug("Skipping option quote fetch; option chain missing", ticker=ticker)
            return {}
        quotes = self._select_reference_quotes(option_chain, bars)
        if use_cache and quotes:
            cache_key = ("alpaca", "option-quote", ticker)
            self.cache.write_json(quotes, *cache_key)
        return quotes

    def collect_news(
        self,
        ticker: str,
        *,
        since: datetime,
        limit: int = 50,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        if not self.enable_news or not self.aggregator.providers:
            return []

        cache_key = ("news", ticker, since.date().isoformat(), str(limit))
        if use_cache and self.cache.exists(*cache_key, suffix=".json"):
            cached = self.cache.read_json(*cache_key)
            return list(cached)

        stories = self.aggregator.gather(ticker, since=since, limit=limit)
        if stories:
            self.cache.write_json(stories, *cache_key)
        return stories

    # ------------------------------------------------------------------- orchestration

    def _select_reference_quotes(
        self,
        option_chain: Any,
        bars: pd.DataFrame | None = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Pick representative call/put contracts near the underlying price."""

        def iter_contracts(chain: Any) -> Iterable[Dict[str, Any]]:
            if isinstance(chain, dict):
                yield from chain.values()
            elif isinstance(chain, list):
                yield from chain
            else:
                return

        price = None
        if isinstance(bars, pd.DataFrame) and not bars.empty and "close" in bars:
            try:
                price = float(bars["close"].astype(float).iloc[-1])
            except (ValueError, TypeError):
                price = None
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        best: Dict[str, Tuple[Tuple[float, float, float], Dict[str, Any]]] = {}
        for contract in iter_contracts(option_chain):
            symbol = str(contract.get("symbol") or "")
            expiration, option_type, strike = _parse_option_symbol(symbol)
            if option_type not in {"CALL", "PUT"} or expiration is None or strike is None:
                continue
            quote = contract.get("latest_quote") or {}
            bid = _sanitize_quote_value(quote.get("bid_price") or quote.get("bid"))
            ask = _sanitize_quote_value(quote.get("ask_price") or quote.get("ask"))
            if ask is None or ask <= 0:
                continue
            if bid is None or bid < 0:
                bid = 0.0
            mid = (bid + ask) / 2 if bid else ask
            exp_dt = expiration if expiration.tzinfo else expiration.replace(tzinfo=timezone.utc)
            days_to_exp = max((exp_dt - now).total_seconds() / 86400.0, 0.0)
            price_diff = abs(strike - price) if price is not None else 0.0
            score = (price_diff, days_to_exp, -bid)
            payload = {
                "symbol": symbol,
                "option_type": option_type,
                "strike": strike,
                "expiration": expiration.isoformat(),
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "source": "alpaca",
            }
            if price is not None:
                payload["underlying_price"] = price
            current = best.get(option_type)
            if current is None or score < current[0]:
                best[option_type] = (score, payload)
        return {opt_type: payload for opt_type, (_, payload) in best.items()}

    def _frame_from_latest_trade(self, ticker: str) -> pd.DataFrame:
        try:
            trade_resp = self.alpaca.fetch_latest_trade(symbol=ticker)
        except APIClientError:
            logger.warning("Latest trade fallback unavailable", ticker=ticker)
            return pd.DataFrame()
        payload = _normalize_trade_payload(trade_resp)
        frame = _frame_from_trade_payload(payload)
        if frame.empty:
            logger.debug("Latest trade payload missing price/timestamp", ticker=ticker)
        else:
            logger.info("Latest trade fallback used for bars", ticker=ticker)
        return frame

    def collect_market_snapshot(
        self,
        *,
        tickers: Optional[Iterable[str]] = None,
        lookback: timedelta = timedelta(days=7),
        news_lookback: timedelta = timedelta(days=2),
        timeframe: str = "1Min",
        use_cache: bool = True,
        include_news: bool = True,
    ) -> Dict[str, Dict[str, Any]]:
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        bar_start = now - lookback
        news_since = now - news_lookback
        snapshot: Dict[str, Dict[str, Any]] = {}
        ticker_list = list(tickers or self.settings.target_tickers)

        for ticker in ticker_list:
            logger.info("Collecting market snapshot", ticker=ticker)
            bars = self.collect_underlying_bars(
                ticker,
                start=bar_start,
                end=now,
                timeframe=timeframe,
                use_cache=use_cache,
            )
            option_chain = self.collect_option_chain(ticker, use_cache=use_cache)
            option_quote = self.collect_option_quote(
                ticker,
                option_chain=option_chain,
                bars=bars,
            )
            news_items: List[Dict[str, Any]] = []
            if include_news:
                news_items = self.collect_news(ticker, since=news_since, use_cache=use_cache)

            snapshot[ticker] = {
                "collected_at": now.isoformat(),
                "underlying_bars": bars,
                "option_chain": option_chain,
                "option_quote": option_quote,
                "news": news_items,
            }
        return snapshot


def _polygon_timespan(timeframe: str) -> str:
    mapping = {
        "1Min": "minute",
        "5Min": "minute",
        "15Min": "minute",
        "1Hour": "hour",
        "1Day": "day",
    }
    return mapping.get(timeframe, "minute")


def _normalize_trade_payload(trade_resp: Any) -> Dict[str, Any]:
    if hasattr(trade_resp, "trade"):
        trade = getattr(trade_resp, "trade")
        if hasattr(trade, "model_dump"):
            return trade.model_dump()
        if hasattr(trade, "__dict__"):
            return dict(trade.__dict__)
    if hasattr(trade_resp, "model_dump"):
        return trade_resp.model_dump()
    if isinstance(trade_resp, dict):
        if "trade" in trade_resp:
            return trade_resp["trade"]
        if len(trade_resp) == 1:
            first = next(iter(trade_resp.values()))
            if hasattr(first, "model_dump"):
                return first.model_dump()
            if hasattr(first, "__dict__"):
                return dict(first.__dict__)
            if isinstance(first, dict):
                return first
        return trade_resp
    return {}


def _frame_from_trade_payload(payload: Dict[str, Any]) -> pd.DataFrame:
    timestamp = payload.get("timestamp")
    price = payload.get("price")
    size = payload.get("size", 0)
    if timestamp is None or price is None:
        return pd.DataFrame()
    if hasattr(timestamp, "isoformat"):
        timestamp = timestamp.isoformat()
    try:
        price = float(price)
        size = float(size or 0.0)
    except (TypeError, ValueError):
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "timestamp": timestamp,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": size,
            }
        ]
    )


def _parse_option_symbol(symbol: str) -> Tuple[Optional[datetime], Optional[str], Optional[float]]:
    """Return expiration, option_type, strike from OCC-style symbols."""

    if len(symbol) < 15:
        return None, None, None
    try:
        date_part = symbol[-15:-9]
        option_type_code = symbol[-9:-8].upper()
        strike_part = symbol[-8:]
        expiration = datetime.strptime(date_part, "%y%m%d")
        option_type = "CALL" if option_type_code == "C" else "PUT" if option_type_code == "P" else None
        strike = int(strike_part) / 1000.0
    except (ValueError, TypeError):
        return None, None, None
    return expiration, option_type, strike


def _sanitize_quote_value(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
